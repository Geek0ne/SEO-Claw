"""百度生态检查项包（market = Market.BAIDU）。

与 base 包的两点区别，都是产品硬要求：

1. **中英文阈值分开**。百度对中文结果的截断按「字符（汉字）」算，30 字左右
   就会被截；英文生态的 60 字符阈值是 Google 那一套，直接套用会让英文站
   或中文长标题被误判。`title.chinese_too_long` 因此只在标题含中日韩字符
   时启用。
2. **只对百度成立的规则才放在这里**。robots 屏蔽、ICP 备案、Viewport 这些
   结论对 Google 市场同样成立，但本项目的市场分流是按站点目标生态做的，
   中文站点扫描时才会带上本包。

每条规则都必须带 evidence；靠「没看到」下结论的规则必须有数据充分性守卫
（`ctx.has_enough_data()`），否则会把「没抓到」当成「不存在」。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from ....models import Issue, Market, Page, Scope, Severity
from ....util import cjk_ratio, contains_han
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()

# 备案查询域名：工信部 ICP + 公安网备，都算「有备案痕迹」
BEIAN_HOSTS = ("beian.miit.gov.cn", "beian.gov.cn", "gaj.mps.gov.cn")

_ICP_TEXT_RE = re.compile(r"[京沪粤津渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵青藏琼宁]\w{0,3}ICP备\d{4,}号?")


# ⚠️ 技术债 #3：原先是独立抄写的一份 `_is_cjk`，与 base / google /
# cnh_eco / i18n 四处重复且语义不一致。现在统一走 util。
# 这里**保持只看汉字**（用 contains_han，不用 contains_cjk）：
# 本包判的是「这是不是中文内容」，若收进谚文/假名，日语站与韩语站会
# 进入百度规则——那是凭空多出来的误报，不是修复。
def _is_cjk(text: str) -> bool:
    return contains_han(text)


def _cjk_ratio(text: str) -> float:
    return cjk_ratio(text)


def _is_japanese(page: Page, extra_text: str = "") -> bool:
    """这个页面是日语的吗？日语不能按中文规则判。

    日文里汉字（kanji）占比很高，「大阪都構想」「内存」这类词中日同形，
    所以光看汉字分不出中日。真正的判据是**假名**：日语必须有假名
    （ひらがな／カタカナ）才能读得出来，中文（以及这条规则面向的
    百度中文生态里的一切）不会用。

    双重判据，`lang` 属性只是其中之一：
    1. `<html lang="ja">` —— 最直接；
    2. 假名字符存在 —— 抗住翻译代理把 lang 属性改写成 zh-CN 的情况。
    """
    if (page.lang or "").lower().split("-")[0] == "ja":
        return True
    sample = f"{page.title or ''}{extra_text}"
    return any(0x3040 <= ord(ch) <= 0x30FF for ch in sample)


def _norm_url(url: str) -> str:
    """URL 归一化，只用于「这个 href 是不是本页」的比对。"""
    return (url or "").strip().rstrip("/").lower()


def _is_translation_view(page: Page) -> bool:
    """当前标题是不是「抓取时协商出来的翻译版」，而不是作者自己写的标题？

    crawler 用 `Accept-Language: zh-CN` 发请求，Discourse 这类站点（以及
    任何接了 Google Translate 的站点）会**把整页机器翻译成中文再返回**：
    `<title>`、`meta description`、`og:*` 全部变成中文，`lang` 也变成 zh-CN。

    翻译版的中文标题不是作者写的，作者也改不了——按它去要求作者改标题，
    等于让人去改一个不存在的东西。实测样本（2026-10 回源核对）：

        meta.discourse.org/t/self-hosters-...-ram-usage/413692
          Accept-Language: en      -> lang=en, title="Self-hosters: Rebuild..."
          Accept-Language: zh-CN   -> lang=zh-CN, title="自托管用户：重新编译..."

    判据（只用 Page 上已有的字段，不改数据层）：
    页面声明了 hreflang，且其中**存在中文变体、却没有任何中文变体指向本页**。
    这正是「本页是源文档，中文是协商出来的」的签名。对照真正的中文本地化页
    atlassian.com/zh/...：它声明 `zh-Hans` 指向自己 → 不是翻译视图，照常判定。
    """
    if not page.hreflang:
        return False
    if (page.lang or "").lower().split("-")[0] != "zh":
        return False
    self_url = _norm_url(page.final_url or page.url)
    has_zh_alternate = False
    for code, href in page.hreflang:
        code = (code or "").lower().replace("_", "-")
        if code != "zh" and not code.startswith("zh-"):
            continue
        has_zh_alternate = True
        if _norm_url(href) == self_url:
            # 本页自己就是被声明的中文版本 → 作者写的中文，照常判定
            return False
    return has_zh_alternate


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------


def _group_rules(directives: list, ua: str) -> tuple[list[str], str]:
    """取某个 UA 生效的规则组。

    robots 协议：UA 专属组优先于 `*` 组；专属组不存在时回退到 `*`。
    """
    exact = [rules for agent, rules in directives if agent == ua]
    if exact:
        # 同一 UA 可能出现多段（罕见），合并处理
        merged: list[str] = []
        for group in exact:
            merged.extend(group)
        return merged, "ua_specific"
    wildcard = [rules for agent, rules in directives if agent == "*"]
    if wildcard:
        merged = []
        for group in wildcard:
            merged.extend(group)
        return merged, "wildcard"
    return [], "none"


def _match(path: str, rules: list[str]) -> tuple[bool, Optional[str]]:
    """robots 匹配：最长匹配前缀生效，同长度 Allow 优先。"""
    best_len = -1
    best_allow = True
    best_rule: Optional[str] = None
    for raw in rules:
        line = raw.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        directive, value = line.split(":", 1)
        directive = directive.strip().lower()
        value = value.strip()
        if directive not in ("allow", "disallow"):
            continue
        if not value:
            # "Disallow:" 空值 = 允许全部；"Allow:" 空值 = 无意义，忽略
            if directive == "disallow":
                return True, None
            continue
        if not path.startswith(value):
            continue
        length = len(value)
        if length > best_len or (length == best_len and directive == "allow"):
            best_len = length
            best_allow = directive == "allow"
            best_rule = f"{directive}: {value}"
    return best_allow, best_rule


def _site_chinese_ratio(pages: list[Page]) -> tuple[float, int]:
    """站点「面向中文用户」的比例：lang=zh* 或正文/标题为中文。"""
    scored = 0
    for p in pages:
        if p.status_code != 200 or not p.is_html or p.error:
            continue
        lang_zh = (p.lang or "").lower().startswith("zh")
        cjk = _cjk_ratio(p.text or p.title or "") > 0.2
        if lang_zh or cjk:
            scored += 1
    total = sum(
        1 for p in pages if p.status_code == 200 and p.is_html and not p.error
    )
    if not total:
        return 0.0, 0
    return scored / total, total


@reg.register
class BaiduspiderNotAllowed(Rule):
    code = "robots.baiduspider_not_allowed"
    # 读 ctx.site_facts（robots.txt 是本轮重新抓的）
    uses_site_facts = True
    market = Market.BAIDU
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "robots.txt 屏蔽了 Baiduspider"
    description = (
        "robots.txt 里针对 Baiduspider（或通配 `*`）写了 Disallow，百度的抓取"
        "机器人就拿不到页面，整站或部分目录不会进入百度索引。"
        "对中文站来说这通常是「复制了海外站 robots」「上线前忘了改」这类疏忽——"
        "但也有站点是刻意只做微信/抖音渠道、不进百度结果的。"
    )
    fix_hint = (
        "把 Baiduspider 组的 Disallow: / 改成 Allow: /，只屏蔽真正不该被索引的路径"
        "（/admin/、/search? 等）；改完到百度搜索资源平台的 robots 工具里验证。"
    )
    fix_example = "User-agent: Baiduspider\nAllow: /\nDisallow: /admin/\nSitemap: https://x.cn/sitemap.xml"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        status = facts.get("robots_status")
        directives = facts.get("robots_directives")
        # 没有 robots 数据就沉默：robots.txt 不存在（404）= 完全放行，不是问题
        if not directives or status != 200:
            return

        rules, source = _group_rules(directives, "baiduspider")
        if not rules:
            return

        # 拿真实页面路径 + 首页做样本，而不是凭空造路径
        paths: list[str] = ["/"]
        seen = {"/"}
        for p in ctx.all_pages:
            if p.status_code != 200 or p.error or not p.is_html:
                continue
            path = urlparse(p.final_url or p.url).path or "/"
            if path not in seen:
                seen.add(path)
                paths.append(path)
            if len(paths) >= 11:
                break

        blocked = []
        for path in paths:
            allowed, rule = _match(path, rules)
            if not allowed:
                blocked.append({"path": path, "matched_rule": rule})

        if not blocked:
            return

        ratio = len(blocked) / len(paths)
        zh_ratio, scored_pages = _site_chinese_ratio(ctx.all_pages)
        whole_site = ratio >= 0.999

        # ↓↓↓ 可能有「有意为之」解释的情况：站点根本不是做百度的 ↓↓↓
        if zh_ratio < 0.5:
            verdict = "possibly_intentional"
            severity = Severity.INFO
            verdict_explain = (
                f"仅 {zh_ratio:.0%} 的页面是中文内容，这个站点看起来不靠百度获取流量，"
                "屏蔽可能是渠道策略的一部分（只做微信/海外流量）。请自行确认。"
            )
        elif whole_site:
            verdict = "likely_unintended"
            severity = Severity.HIGH
            verdict_explain = (
                f"{zh_ratio:.0%} 的页面是中文内容，说明站点目标用户在中国大陆，"
                "却全站屏蔽了 Baiduspider——意图与配置相互矛盾，大概率是疏忽。"
            )
        else:
            verdict = "likely_unintended_partial"
            severity = Severity.MEDIUM
            verdict_explain = (
                f"只屏蔽了 {ratio:.0%} 的样本路径（常见于「屏蔽参数页」时手滑写成了根路径），"
                "中文内容为主却挡住部分收录路径，建议逐条确认是否有意。"
            )

        yield self._site_issue(
            ctx,
            {
                "robots_url": facts.get("robots_url"),
                "robots_status": status,
                "matched_group": source,
                "baiduspider_rules": [r for r in rules if ":" in r],
                "sampled_paths": len(paths),
                "blocked_count": len(blocked),
                "blocked_ratio": round(ratio, 3),
                "blocked_examples": blocked[:8],
                "whole_site_blocked": whole_site,
                "chinese_page_ratio": round(zh_ratio, 3),
                "pages_scored": scored_pages,
                "verdict": verdict,
                "verdict_explain": verdict_explain,
            },
            severity=severity,
        )


def _is_emoji(ch: str) -> bool:
    """emoji / 符号类区块，实际渲染接近全宽。"""
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2B00 <= cp <= 0x2BFF
        or 0x1F1E6 <= cp <= 0x1F1FF
    )


def _is_wide(ch: str) -> bool:
    """全角字符：汉字、假名、全角标点、全角字母等（每个 1em）。"""
    return unicodedata.east_asian_width(ch) in ("W", "F")


# 半角字符宽度表（16px 基准无衬线字体的经验值）。
# ⚠️ 这张表与 `app/audit/rules/google/__init__.py` 里的 `_W_*` 同源，**必须保持同步**。
#   之前试过直接 `from ..google import _estimate_title_px` 复用，但两个市场包
#   互相 import 会构成环（google.i18n → google → baidu），直接让整个规则
#   注册表加载失败、251 个测试全红。现文件是独占修改范围，无法把共用函数上提，
#   所以只能在这端口一份——这是已知的技术债，改 google 包时需同步这里。
_W_NARROW = set("iljItf.,;:'!|()[]-·’‘“”\"`")
_W_UPPER = 10.7
_W_LOWER = 8.0
_W_DIGIT = 8.9
_W_SPACE = 4.4
_W_PUNCT = 5.5
_W_OTHER_ALPHA = 9.0
_W_EMOJI = 16.0
_W_CURLY = set("“”‘’")


def _char_px(ch: str, curly_w: float) -> float:
    cp = ord(ch)
    # 变体选择符 / ZWJ 不占宽度
    if cp == 0x200D or 0xFE00 <= cp <= 0xFE0F:
        return 0.0
    if _is_emoji(ch):
        return _W_EMOJI
    if _is_wide(ch):
        return _W_EMOJI
    if ch in _W_CURLY:
        return curly_w
    if ch.isspace():
        return _W_SPACE
    if ch in _W_NARROW:
        return 4.5
    if ch.isdigit():
        return _W_DIGIT
    if ch.isalpha():
        if ch.isascii():
            return _W_UPPER if ch.isupper() else _W_LOWER
        return _W_OTHER_ALPHA
    return _W_PUNCT


def _title_px(title: str) -> float:
    """标题在搜索结果里的渲染宽度（px）。

    百度结果页的标题是**按像素宽度截断**的，约 30 个汉字——不是按字符数。
    汉字 1em = 16px，所以预算 = 30 × 16 = 480px（见 ChineseTitleTooLong）。

    旧实现用 `len(title)`，等于把半角 ASCII 也当 1em 算，白送预算。实测误报样本
    （2026-10 回源核对，均为真实回访数据）：

        「借助 Statuspage 提高透明度 | Atlassian」            31 字符 → 274px
        「关于零售商 | 查找店铺库存 | Bellroy零售商及销售点」  31 字符 → 366px

    两者都远在 480px 之内，百度根本不会截断，却都被判成超长。
    注意方向：这是把**算错的测量**改对，不是把上限往上抬——31 个纯汉字
    （496px）依旧照报。
    """
    # 中文排版里 “” 是全角，英文里是窄的
    curly_w = _W_EMOJI if any(_is_wide(c) for c in title) else 4.5
    return sum(_char_px(ch, curly_w) for ch in title)


def _visible_prefix_by_px(title: str, budget_px: float) -> str:
    """按像素预算切出可见前缀，与实际截断行为一致。"""
    curly_w = _W_EMOJI if any(_is_wide(c) for c in title) else 4.5
    out = ""
    used = 0.0
    for ch in title:
        w = _char_px(ch, curly_w)
        if used + w > budget_px:
            break
        out += ch
        used += w
    return out


# --------------------------------------------------------------------------
# 中文 title
# --------------------------------------------------------------------------


@reg.register
class ChineseTitleTooLong(Rule):
    code = "title.chinese_too_long"
    market = Market.BAIDU
    severity = Severity.MEDIUM
    title = "中文 title 超过 30 字会被百度截断"
    description = (
        "百度搜索结果标题的显示上限约 30 个汉字（含标点），超出的部分直接截断，"
        "并用省略号收尾。中文标题的可用字符数本来就比英文少，"
        "把品牌名、卖点全塞进去往往只剩前半截被展示。"
    )
    fix_hint = "把核心关键词放最前面，控制在 30 字以内；品牌名和副标题能砍就砍。"
    fix_example = "防水登山鞋 男款防滑耐磨 - 登山者（18 字）"

    # 百度结果页标题的显示宽度上限：约 30 个汉字（= 30 × 16px = 480px）
    LIMIT = 30
    BUDGET_PX = 480.0

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.title:
            return
        # ★ 阈值分离：只有含中日韩字符的标题才用中文阈值。
        #   纯英文/数字标题走 base 包的 60 字符阈值，这里必须保持沉默。
        if not _is_cjk(page.title):
            return
        # ★ 作用域一：日语不按中文规则判。中日汉字同形，日文标题里汉字
        #   占比很高，`_is_cjk` 必然放行，但中文 SERP 的截断规律套不上去。
        if _is_japanese(page):
            return
        # ★ 作用域二：抓取时协商出来的翻译版，中文标题不是作者写的。
        if _is_translation_view(page):
            return

        px = _title_px(page.title)
        if px <= self.BUDGET_PX:
            return

        shown = _visible_prefix_by_px(page.title, self.BUDGET_PX)
        length = page.title_length or len(page.title)
        yield self._issue(
            page,
            {
                "title": page.title,
                "length": length,
                "estimated_px": round(px, 1),
                "budget_px": self.BUDGET_PX,
                "limit_zh": self.LIMIT,
                "limit_en": 60,
                "visible_prefix": shown,
                "truncated_tail": page.title[len(shown) :],
                "overflow_px": round(px - self.BUDGET_PX, 1),
                "note": (
                    "按 SERP 渲染宽度判定（复用 google 包的像素宽度表），"
                    "预算 480px = 30 个汉字；本条只对含中日韩字符、"
                    "且非日语、非抓取翻译版的标题生效；"
                    "纯英文标题请看 title.too_long（60 字符阈值）"
                ),
            },
        )


# --------------------------------------------------------------------------
# 中文语义完整性
# --------------------------------------------------------------------------


@reg.register
class ChineseSemanticIncomplete(Rule):
    code = "meta.chinese_semantic_incomplete"
    market = Market.BAIDU
    severity = Severity.INFO
    title = "title/description 像关键词堆砌，没有完整语义"
    description = (
        "同一个中文词根在标题或描述里连续出现 3 次以上，是「关键词堆砌」的典型特征。"
        "百度早年确实吃这套，但现在这类页面在搜索结果里可读性差、跳出率高，"
        "对权重是负面的。"
        "⚠️ 判定基于词根重复次数，属统计信号而非语法分析——"
        "老式中文 SEO 也常用这种「关键词 - 关键词 - 关键词」列表式标题，"
        "如果确实带来过流量，保留也没问题。"
    )
    fix_hint = "改写成一句完整的话：先回答「这是什么」，再说「为什么选它」。"

    _MIN_REPEATS = 3
    _GRAM_LENS = (2, 3, 4)

    def _repeated_terms(self, text: str) -> dict[str, int]:
        if not text or not _is_cjk(text):
            return {}
        counts: dict[str, int] = {}
        for n in self._GRAM_LENS:
            c = Counter(
                text[i : i + n]
                for i in range(len(text) - n + 1)
                if _is_cjk(text[i : i + n])
            )
            for gram, num in c.items():
                if num >= self._MIN_REPEATS:
                    counts[gram] = num
        # 只保留「最长」的重复词根：被更长重复词根包含的短词根是噪声
        return {
            g: n
            for g, n in counts.items()
            if not any(g != other and g in other for other in counts)
        }

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200:
            return
        # ★ 作用域一：日语不按中文规则判。这条规则跑的是中文 2/3/4-gram 词根
        #   统计，中文文本的切分规律在日文上不成立——而且日文汉字与中文同形，
        #   「大阪」「内存」这类词根在正常日文新闻里重复出现是极自然的，
        #   n-gram 一律误判。实测样本：朝日新闻标题里的「大阪」重复 4 次。
        if _is_japanese(page, page.meta_description or ""):
            return
        # ★ 作用域二：抓取时协商出来的翻译版，中文不是作者写的语言。
        if _is_translation_view(page):
            return
        title_terms = self._repeated_terms(page.title or "")
        desc_terms = self._repeated_terms(page.meta_description or "")
        if not title_terms and not desc_terms:
            return

        yield self._issue(
            page,
            {
                "title": page.title,
                "title_length": page.title_length,
                "title_repeated_terms": title_terms,
                "meta_description": (page.meta_description or "")[:200],
                "meta_description_repeated_terms": desc_terms,
                "min_repeats": self._MIN_REPEATS,
                "gram_lengths_checked": list(self._GRAM_LENS),
                "repeated_in": (
                    "title"
                    if title_terms and not desc_terms
                    else "meta_description"
                    if desc_terms and not title_terms
                    else "title_and_meta_description"
                ),
                "verdict": "likely_keyword_stuffing",
                "verdict_explain": (
                    "同一中文词根重复出现 ≥3 次。中文搜索引擎生态里这是公认的堆砌写法，"
                    "但也不排除是有意为之的老式列表式标题——请以实际搜索表现为准。"
                ),
            },
        )


# --------------------------------------------------------------------------
# ICP 备案
# --------------------------------------------------------------------------


@reg.register
class IcpFilingMissing(Rule):
    code = "icp.filing_missing"
    market = Market.BAIDU
    severity = Severity.INFO
    scope = Scope.SITE
    title = "未发现 ICP 备案信息（面向大陆的站点需备案）"
    description = (
        "在中国大陆境内提供的网站必须完成 ICP 备案，否则会被接入商关停；"
        "百度对未备案站点的收录质量与排序也普遍更差。"
        "本页只在「站点明显面向大陆 + 全站找不到备案痕迹」时提示。"
        "⚠️ 重要限制：正文抽取器会剥掉页脚，纯文本形式的备案号可能因此看不到，"
        "所以这条只给 INFO，请人工到页脚确认一次。"
    )
    fix_hint = (
        "到工信部 ICP 备案系统查询确认；页脚放上备案号并链接到 "
        "https://beian.miit.gov.cn/（公安备案还需挂 gaj 号）。"
    )
    fix_example = '<a href="https://beian.miit.gov.cn/">京ICP备12345678号-1</a>'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ★ 数据充分性门槛：本规则靠「全站没看到备案」下结论。
        #   只抓到几页时，「没发现」只是没抓到——必须先确认覆盖足够。
        if not ctx.has_enough_data():
            return

        domain = ctx.domain.lower()
        pages = [p for p in ctx.all_pages if p.status_code == 200 and p.is_html and not p.error]
        if not pages:
            return

        zh_ratio, _ = _site_chinese_ratio(ctx.all_pages)
        mainland_hint = domain.endswith(".cn") or zh_ratio >= 0.5
        if not mainland_hint:
            # 站点目标不在大陆：没有备案是正常的，不提。
            return

        hits: list[dict[str, Any]] = []
        for p in pages:
            for link in p.links:
                host = urlparse(link.href).netloc.lower()
                if any(host == h or host.endswith("." + h) for h in BEIAN_HOSTS):
                    hits.append({"type": "link", "url": p.url, "value": link.href})
                    break
            if _ICP_TEXT_RE.search(p.text or ""):
                hits.append({"type": "text", "url": p.url, "value": _ICP_TEXT_RE.search(p.text or "").group(0)})
        if hits:
            return

        yield self._site_issue(
            ctx,
            {
                "domain": ctx.domain,
                "mainland_signal": {
                    "tld_cn": domain.endswith(".cn"),
                    "chinese_page_ratio": round(zh_ratio, 3),
                },
                "pages_checked": len(pages),
                "beian_links_found": 0,
                "coverage": round(ctx.coverage, 3),
                "verdict": "likely_missing_or_unlinked",
                "verdict_explain": (
                    f"扫描了 {len(pages)} 页（覆盖率 {ctx.coverage:.0%}），"
                    "全站未发现指向 beian.miit.gov.cn 的链接，正文里也没有 ICP 号。"
                    "注意：页脚纯文本备案号会被正文抽取器剥离，因此这条是提醒不是定论——"
                    "请人工看一眼首页页脚。"
                ),
                "lookups": [
                    "工信部备案查询 https://beian.miit.gov.cn/",
                    "首页页脚是否有「XXICP备XXXXXXX号」",
                ],
            },
        )


# --------------------------------------------------------------------------
# 移动适配
# --------------------------------------------------------------------------


@reg.register
class MobileLandingPageMissing(Rule):
    code = "mobile.landing_page_missing"
    market = Market.BAIDU
    severity = Severity.HIGH
    title = "页面缺少 viewport，移动端会被缩成桌面版"
    description = (
        "没有 `<meta name=\"viewport\">` 时，手机浏览器会用一个约 980px 的虚拟宽度"
        "渲染页面再整体缩小：字小到要点开才能读，点不准按钮。"
        "百度的移动端检索与落地页评估（移动友好度）也直接看这条。"
    )
    fix_hint = "在 <head> 里加一行响应式 viewport。"
    fix_example = '<meta name="viewport" content="width=device-width, initial-scale=1">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.is_html:
            return
        if page.viewport:
            return

        # ↓↓↓ 可能有「有意为之」解释：站点另有独立移动站 ↓↓↓
        mobile_links = [
            l.href
            for l in page.links
            if urlparse(l.href).netloc.lower().startswith(("m.", "wap.", "3g."))
        ]
        if mobile_links:
            severity = Severity.MEDIUM
            verdict = "possibly_separate_mobile_site"
            verdict_explain = (
                "页面上存在独立移动域名的链接（"
                f"{mobile_links[0][:60]}），如果用户被引导到 m./wap. 站，"
                "桌面页缺 viewport 可能是刻意的。确认一下实际投放链接指向哪里。"
            )
        else:
            severity = Severity.HIGH
            verdict = "likely_missing"
            verdict_explain = "页面上没有发现独立移动站的链接，移动端大概率直接吃这个页面。"

        yield self._issue(
            page,
            {
                "viewport_found": False,
                "url": page.final_url or page.url,
                "lang": page.lang,
                "mobile_domain_links": mobile_links[:5],
                "word_count": page.word_count,
                "verdict": verdict,
                "verdict_explain": verdict_explain,
            },
            severity=severity,
        )
