"""
规则引擎：所有 SEO 检查项的执行框架。

核心约定
--------
1. 规则分 PAGE / SITE 两种作用域，引擎分两阶段执行。
2. 每条 Issue 必须带 evidence —— 没有证据的结论不允许输出。
3. 规则按 market 分包注册，新增市场 = 新增包，不改引擎。
4. 规则必须确定性：不发网络请求、不调 LLM、不依赖时间或随机数。
"""

from __future__ import annotations

import importlib
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from ..models import Issue, Market, Page, Scope, Severity


@dataclass
class RuleContext:
    """SITE 级规则需要全站数据，通过 context 传入。"""

    domain: str
    markets: list[Market] = field(default_factory=list)
    all_pages: list[Page] = field(default_factory=list)
    # 由 site 级规则在上游预先算好的索引，避免每条规则重算 O(n^2)
    title_index: dict[str, list[str]] = field(default_factory=dict)
    meta_index: dict[str, list[str]] = field(default_factory=dict)
    inbound_links: dict[str, int] = field(default_factory=dict)
    # 爬虫阶段探测到的站点级事实（sitemap 是否存在、有多少 URL、robots 状态等）
    # 站点级规则靠它判断「该有的东西没有」，不自己发网络请求。
    site_facts: dict[str, Any] = field(default_factory=dict)
    # ★ 数据充分性：某些结论（如「这个页面是孤岛页」）只有在抓取覆盖足够
    # 时才成立。覆盖率不够时规则必须保持沉默，否则会大面积误报。
    crawled: int = 0
    discovered: int = 0
    hit_page_limit: bool = False

    @property
    def coverage(self) -> float:
        """抓取覆盖率。0~1。"""
        return min(1.0, self.crawled / max(self.discovered, 1))

    def has_enough_data(self, min_coverage: float = 0.5, min_pages: int = 20) -> bool:
        """数据是否足够支撑「全局性缺失」类结论。

        ⚠️ 只适用于靠「**没看到**」下结论的规则（如孤岛页：
        我没发现指向它的内链）。这类结论必须先确信「大部分页面都看到了」，
        否则「没发现」只是因为「没抓到」。

        不适用于靠**正面证据**的规则：看到两个页面 title 相同就是重复，
        哪怕只抓了 2 个页面也成立。（这个区分踩过坑，一开始把门槛
        也加在 title.duplicate 上，被测试直接抓出来。）
        """
        if self.hit_page_limit:
            return False  # 撞到上限就说明没抓完
        return self.crawled >= min_pages and self.coverage >= min_coverage


class Rule(ABC):
    """所有检查项的基类。"""

    code: str = ""
    market: Market = Market.BASE
    severity: Severity = Severity.MEDIUM
    scope: Scope = Scope.PAGE
    title: str = ""
    description: str = ""
    fix_hint: str = ""
    fix_example: Optional[str] = None
    # 本规则是否读取 ctx.site_facts（robots/sitemap/回访结果这类**本次扫描**的事实）。
    #
    # ⚠️ 增量扫描的跳过判定靠它：服务器回 304 的页面复用了上一轮解析结果，
    # 但 site_facts 是本轮重新抓的。这类规则即使页面没变也**必须重跑**——
    # 跳过就等于让昨天的 robots.txt 结论替今天的文件背书。
    # 加新规则时读 site_facts 就必须置 True，否则增量模式会静默给过期结论。
    uses_site_facts: bool = False

    @abstractmethod
    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        """执行检查，返回该页面（或该站点）的问题列表。"""
        raise NotImplementedError

    # -- 给子类用的便捷方法 ------------------------------------------------

    def _issue(self, page: Page, evidence: dict[str, Any], **overrides: Any) -> Issue:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "market": self.market,
            "scope": self.scope,
            "url": page.url,
            "title": self.title,
            "description": self.description,
            "fix_hint": self.fix_hint,
            "fix_example": self.fix_example,
            "evidence": evidence,
        }
        payload.update(overrides)
        return Issue(**payload)

    def _site_issue(self, ctx: RuleContext, evidence: dict[str, Any], **kw: Any) -> Issue:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "market": self.market,
            "scope": self.scope,
            "url": None,
            "title": self.title,
            "description": self.description,
            "fix_hint": self.fix_hint,
            "fix_example": self.fix_example,
            "evidence": evidence,
        }
        payload.update(kw)
        return Issue(**payload)


class RuleRegistry:
    """规则注册表。按 market 组织，支持按站点市场过滤加载。"""

    def __init__(self) -> None:
        self._page_rules: list[Rule] = []
        self._site_rules: list[Rule] = []

    def register(self, rule_cls: type[Rule]) -> type[Rule]:
        """把规则类实例化并注册。可作装饰器使用。"""
        rule = rule_cls()
        if not rule.code:
            raise ValueError(f"规则 {rule_cls.__name__} 缺少 code")
        target = self._site_rules if rule.scope is Scope.SITE else self._page_rules
        target.append(rule)
        return rule_cls

    def load_module_rules(self, module: Any) -> int:
        """从模块（含包的子模块）中加载所有 Rule 子类并注册，返回注册数量。

        新增一个检查项只要写个类放进 rules/ 目录即可，引擎和调用方都不用改。

        ⚠️ 必须递归扫子模块：只扫包的 __init__.py 的话，
        写在 rules/google/i18n.py 这类兄弟文件里的规则会「文件存在、规则不注册」，
        变成死代码——而且测试照样全绿，因为没人在测「规则有没有被注册上」。
        这个坑真的踩过。
        """
        count = 0
        seen: set[str] = set()

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Rule)
                and obj is not Rule
                and obj.__module__ == module.__name__
                and getattr(obj, "code", "")
            ):
                self.register(obj)
                count += 1
                seen.add(obj.__module__)

        # 递归子模块（跳过 __init__ 自身，避免重复注册）
        pkg_paths = getattr(module, "__path__", None)
        if pkg_paths:
            import pkgutil

            prefix = f"{module.__name__}."
            for _finder, name, _ispkg in pkgutil.iter_modules(pkg_paths, prefix):
                if name in seen or name.endswith(".__init__"):
                    continue
                try:
                    sub = importlib.import_module(name)
                except Exception as exc:  # noqa: BLE001
                    # 子模块导入失败不应让整个规则集挂掉，但必须留下痕迹，
                    # 否则会退化成「静默少几条规则」的最难查故障
                    print(f"⚠️ 规则子模块 {name} 导入失败，已跳过: {exc}")
                    continue
                count += self.load_module_rules(sub)
        return count

    def page_rules_for(self, markets: Iterable[Market]) -> list[Rule]:
        allowed = set(markets) | {Market.BASE}
        return [r for r in self._page_rules if r.market in allowed]

    def site_rules_for(self, markets: Iterable[Market]) -> list[Rule]:
        allowed = set(markets) | {Market.BASE}
        return [r for r in self._site_rules if r.market in allowed]


def build_context(
    domain: str,
    pages: list[Page],
    markets: list[Market] | None = None,
    site_facts: dict[str, Any] | None = None,
) -> RuleContext:
    from collections import defaultdict

    title_index: dict[str, list[str]] = defaultdict(list)
    meta_index: dict[str, list[str]] = defaultdict(list)
    inbound: dict[str, int] = defaultdict(int)

    for p in pages:
        if p.status_code != 200 or not p.is_html:
            continue
        if p.title:
            title_index[p.title].append(p.url)
        if p.meta_description:
            meta_index[p.meta_description].append(p.url)
        for link in p.links:
            if link.kind.value == "internal":
                inbound[link.href] += 1

    site_facts = site_facts or {}
    return RuleContext(
        domain=domain,
        markets=markets or [Market.BASE],
        all_pages=pages,
        title_index={k: v for k, v in title_index.items() if len(v) > 1},
        meta_index={k: v for k, v in meta_index.items() if len(v) > 1},
        inbound_links=dict(inbound),
        site_facts=site_facts,
        crawled=len(pages),
        discovered=int(site_facts.get("discovered_count") or len(pages) or 1),
        hit_page_limit=bool(site_facts.get("hit_page_limit")),
    )


def run_audit(
    pages: list[Page],
    domain: str,
    markets: list[Market] | None = None,
    site_facts: dict[str, Any] | None = None,
    incremental: bool = False,
) -> tuple[list[Issue], RuleContext]:
    """执行完整审计，返回去重后的问题列表。

    PAGE 级规则逐页跑；SITE 级规则基于全站索引跑一次。

    ``incremental=True`` 时启用增量跳过：服务器回 304（``page.not_modified``）
    的页面复用上一轮结论。见 ``_skip_page_rules`` 里的两条硬约束——
    跳过这件事比看起来危险得多，条件写错就是**静默给出过期结论**。
    """
    markets = markets or [Market.BASE]
    ctx = build_context(domain, pages, markets, site_facts)

    registry = default_registry()
    issues: list[Issue] = []
    skip_urls = _skip_page_rules(pages) if incremental else frozenset()

    for rule in registry.page_rules_for(markets):
        for page in pages:
            if not page.is_html or page.error:
                continue
            if page.url in skip_urls and not rule.uses_site_facts:
                continue
            try:
                issues.extend(rule.check(page, ctx))
            except Exception as exc:  # noqa: BLE001 — 单条规则挂掉不能拖垮整次扫描
                issues.append(
                    Issue(
                        code=f"rule.error.{rule.code}",
                        severity=Severity.INFO,
                        market=rule.market,
                        scope=rule.scope,
                        url=page.url,
                        title=f"规则执行失败：{rule.code}",
                        description=f"内部错误：{exc}",
                        evidence={"rule": rule.code, "error": str(exc)},
                    )
                )

    for rule in registry.site_rules_for(markets):
        try:
            # SITE 级规则的 check() 里不读 page 参数（用 ctx.all_pages），传哨兵即可
            issues.extend(rule.check(_EMPTY_PAGE, ctx))
        except Exception as exc:  # noqa: BLE001
            issues.append(
                Issue(
                    code=f"rule.error.{rule.code}",
                    severity=Severity.INFO,
                    market=rule.market,
                    scope=rule.scope,
                    title=f"规则执行失败：{rule.code}",
                    description=f"内部错误：{exc}",
                    evidence={"rule": rule.code, "error": str(exc)},
                )
            )

    return dedupe(issues), ctx


def _skip_page_rules(pages: list[Page]) -> frozenset[str]:
    """增量模式下，哪些页面的页面级规则可以跳过。返回 URL 集合（空 = 全跑）。

    ⚠️ 两条硬约束，少一条就会**静默给出过期结论**——用户看不出报告是旧的，
    而这是比误报更坏的一种错：

    1. **只要有任一页面变了，全站页面级规则都得重跑。**
       跨页规则（``title.duplicate`` 靠全站同名索引、孤岛页靠 inbound_links、
       全站索引类）的结论由**别的页面**决定。A 页改了标题，B 页的
       「是否重复」就可能翻转——哪怕 B 页自己是304 未变。
       只按 B 页自身有没有变来决定跳不跳，结论必然错。
       所以增量跳过只在「全站零变化」时才允许生效。

    2. ``not_modified`` 只能来自 304。抓取失败页（timeout/429/403）**没有**
       任何可信结论，绝不能因为「这次也没抓到」就跳过——那等于把
       「上次抓到的旧结论」当成「本次检查结果」。
    """
    if not pages:
        return frozenset()
    if any(not p.not_modified for p in pages):
        return frozenset()  # 约束 1：有变化就全跑
    return frozenset(
        p.url
        for p in pages
        if p.not_modified and p.status_code == 200 and not p.error
    )  # 约束 2：只跳过「服务器说没变」且上次确实抓成功了的页


_EMPTY_PAGE = Page(url="about:blank", status_code=0, is_html=False)


def dedupe(issues: list[Issue]) -> list[Issue]:
    """同一 code + URL 只保留最严重的一条，并按严重度排序。"""
    best: dict[tuple[str, str | None], Issue] = {}
    for issue in issues:
        key = issue.dedup_key()
        current = best.get(key)
        if current is None or issue.severity.rank < current.severity.rank:
            best[key] = issue
    return sorted(best.values(), key=lambda i: (i.severity.rank, i.code, i.url or ""))


# --------------------------------------------------------------------------
# 内置规则注册表
# --------------------------------------------------------------------------

_registry: RuleRegistry | None = None


def default_registry() -> RuleRegistry:
    """加载全部规则包，返回全局单例。"""
    global _registry
    if _registry is not None:
        return _registry

    registry = RuleRegistry()
    # base 包：所有市场通用的检查项
    registry.load_module_rules(_import_rules("base"))
    # google / baidu / cnh_eco 包在对应市场启用时加载
    for name in ("google", "baidu", "cnh_eco"):
        try:
            registry.load_module_rules(_import_rules(name))
        except ModuleNotFoundError:
            pass

    _registry = registry
    return registry


def _import_rules(pkg: str) -> Any:
    import importlib

    return importlib.import_module(f".rules.{pkg}", package=__package__)


def reset_registry() -> None:
    """测试用：清空单例。"""
    global _registry
    _registry = None
