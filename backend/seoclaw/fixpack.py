"""处方包（Fix Pack）—— 从「体检报告」到「照着改的整改工单」。

## 为什么需要这一层

体检报告回答的是「哪里不对、为什么有害」；用户真正要付钱买的是
「下周一我改什么、改成什么样」。本模块把规则引擎的 ``Issue`` 变成
**可直接落地的修复动作**：字段级的「改前 → 改后」+ 怎么落进站点。

这是产品从「体检工具」跨到「执行型 Agent」的第一步：
报告说「title 过长」，工单直接给出裁好的 title。

## 三条硬规矩（与规则引擎同源）

1. **产出分三档可信度，绝不冒充**：
   - ``deterministic`` —— 取值机械可得（自指 canonical、viewport 常量、
     按文件名生成 alt），照抄不会错；
   - ``heuristic`` —— 机器起草的文案（title/meta 改写），**必须人工润色后
     才能发布**。宁可标丑，也不让「机器写的」伪装成「已定稿」；
   - ``recipe`` —— 只给配方（robots.txt / sitemap / JSON-LD），涉及站点
     结构与运维，工具无权代填。
2. **改写只用确定性信息**（页面现有字段 + 正文），不引入 LLM：
   规则层永不依赖 LLM 是 PLAN 的铁律 #2，处方层同理——没有 API key
   的用户也必须拿到工单。
3. **判不了的不硬凑**：无法安全改写的字段进 ``manual_review``，
   带上原问题的 fix_hint，让人接着做。沉默好过瞎改。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .models import Issue, Page, Severity


class Confidence(str, Enum):
    """处方产出的可信度分档。见模块 docstring 第 1 条。"""

    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"
    RECIPE = "recipe"


CONFIDENCE_LABEL = {
    Confidence.DETERMINISTIC: "可直接照抄",
    Confidence.HEURISTIC: "机器起草，发布前请人工润色",
    Confidence.RECIPE: "配方，需结合站点结构落地",
}


class FixAction(BaseModel):
    """一条可落地的修复动作。"""

    url: Optional[str] = None  # None = 站点级（robots/sitemap/og 这类）
    code: str  # 触发它的规则 code，保证处方与诊断对得上
    field: str  # title / meta_description / h1 / canonical / ...
    before: Optional[str] = None
    after: str
    how_to: str = ""  # 怎么落到站点上（放哪、改哪、注意什么）
    confidence: Confidence = Confidence.HEURISTIC
    pages_affected: int = 1  # 站点级处方按「波及多少页」标价


class FixPack(BaseModel):
    """一个站点的整改工单。"""

    domain: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pages_considered: int = 0
    actions: list[FixAction] = Field(default_factory=list)
    manual_review: list[Issue] = Field(default_factory=list)
    # 工单自身的诚实声明：覆盖率、哪些字段库里没有、哪些结论降级处理
    notes: list[str] = Field(default_factory=list)

    @property
    def by_confidence(self) -> dict[Confidence, list[FixAction]]:
        out: dict[Confidence, list[FixAction]] = {c: [] for c in Confidence}
        for a in self.actions:
            out[a.confidence].append(a)
        return out


# --------------------------------------------------------------------------
# 文案改写的确定性工具
# --------------------------------------------------------------------------

# meta description 预算。中文按字、英文按字符——与 title 同一套判据思路
# （base 规则 title 阈值 30/60，这里 description 取搜索结果不截断的安全区）。
_META_LIMIT_CJK = 78
_META_LIMIT_LATIN = 155
_TITLE_LIMIT_CJK = 30
_TITLE_LIMIT_LATIN = 60


def _is_cjk_text(text: str) -> bool:
    """按多数字符判断中日韩文本——同 util.contains_cjk 的判据精神，
    但这里要的是「按哪种预算裁」，所以看占比而不是「出现过就算」。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk * 2 >= max(len(text), 1)


def _clip(text: str, limit: int, *, ellipsis: str = "…") -> str:
    """按预算裁剪，尽量不把词从中间切断。

    英文在词边界裁，中文直接按字裁（中文没有空格词边界）。
    裁掉的信息不找补——过长 title 的正确修法本来就是「只留最重要的」，
    自动续写只会制造新的堆砌。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: max(limit - len(ellipsis), 1)]
    if not _is_cjk_text(text):
        # 英文回退到最后一个空格，避免半个单词
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
    return cut.rstrip(" -_|、，,;；") + ellipsis


def _strip_site_suffix(title: str, suffixes: Iterable[str]) -> str:
    """剥掉 title 尾部的站点名（「页面名 - 品牌名」「页面名 | 品牌名」）。

    过长/重复 title 的改写都要先把「每个页面都一样的尾巴」剥掉——
    那是占预算的大头，也是重复的元凶。剥不掉就原样返回，不硬猜。
    """
    for suf in suffixes:
        for sep in (" - ", " | ", "｜", " – ", " — ", "_"):
            tail = f"{sep}{suf}"
            if title.endswith(tail):
                return title[: -len(tail)].strip()
    return title.strip()


def _detect_site_suffix(pages: list[Page]) -> Optional[str]:
    """从整站 title 分布里发现「站点名尾巴」。

    只认「多数页面共有的结尾」：一半以上页面以同一个「分隔符 + 短语」
    结尾才认定它是品牌尾巴。这是正面证据（真有这么个尾巴），
    不是「我觉得像」。
    """
    from collections import Counter

    tails: Counter = Counter()
    total = 0
    for p in pages:
        t = (p.title or "").strip()
        if not t:
            continue
        total += 1
        for sep in (" - ", " | ", "｜", " – ", " — "):
            if sep in t:
                tail = t.rsplit(sep, 1)[1].strip()
                if 0 < len(tail) <= 25:
                    tails[tail] += 1
                break
    if not total:
        return None
    tail, n = tails.most_common(1)[0] if tails else (None, 0)
    return tail if tail and n * 2 > total else None


_SENT_END = ("。", "！", "？", ".", "!", "?")


def _first_sentences(text: str, limit: int) -> str:
    """从正文里取开头到第一个句末标点（或预算上限），作为 description 底稿。"""
    text = " ".join((text or "").split())
    if not text:
        return ""
    out = ""
    for i, ch in enumerate(text):
        out += ch
        if ch in _SENT_END and i >= 8:  # 至少 8 字，避免「首页。」这种废句
            break
        if len(out) >= limit:
            break
    return _clip(out, limit)


def _derive_title(page: Page, domain: str, suffix: Optional[str]) -> str:
    """缺 title 时的底稿来源，按证据强度排序：H1 > 小标题 > 正文首句 > 域名。"""
    base = ""
    if page.h1:
        base = page.h1[0].strip()
    if not base:
        for level, text in page.headings:
            if text.strip():
                base = text.strip()
                break
    if not base:
        base = _first_sentences(page.text, _TITLE_LIMIT_LATIN) or domain
    return base


def _title_budget(page: Page) -> int:
    sample = page.title or (page.h1[0] if page.h1 else "")
    return _TITLE_LIMIT_CJK if _is_cjk_text(sample) else _TITLE_LIMIT_LATIN


# --------------------------------------------------------------------------
# 处方生成
# --------------------------------------------------------------------------

# 能直接给「字段改后值」的页面级规则。映射到生成函数，其余进 manual_review。
# ⚠️ 加规则先想清楚「after 是机械可得还是拍脑袋」——拍脑袋的只能给 recipe。
_PAGE_FIELD_CODE = {
    "title.missing": "title",
    "title.too_long": "title",
    "title.chinese_too_long": "title",
    "title.pixel_overflow": "title",
    "title.too_short": "title",
    "meta.missing": "meta_description",
    "h1.missing": "h1",
    "h1.multiple": "h1",
    "canonical.missing": "canonical",
    "lang.missing": "html_lang",
    "viewport.missing": "viewport",
    "img.alt.missing": "img_alt",
    "img.alt.generic": "img_alt",
}

# 站点级、给配方的规则：工具无法代填（涉及运维），但必须给出可照抄的模板
_RECIPE_CODES = {
    "robots.missing": "robots_txt",
    "sitemap.missing": "sitemap",
    "schema.missing": "jsonld",
    "og.basic_missing": "open_graph",
    "noindex.present": "noindex_review",
    "robots.blocks_own_site": "robots_txt",
}

_VIEWPORT = "width=device-width, initial-scale=1"


def _fix_title(
    page: Page, code: str, suffix: Optional[str]
) -> tuple[Optional[str], str, str, Confidence]:
    title = (page.title or "").strip()
    budget = _TITLE_LIMIT_CJK if _is_cjk_text(title or _derive_title(page, "", suffix)) else _TITLE_LIMIT_LATIN

    if code == "title.missing":
        base = _derive_title(page, urlparse(page.url).netloc, suffix)
        after = f"{base} - {suffix}" if suffix and suffix not in base else base
        after = _clip(after, budget)
        how_to = "把下面的值写进该页 <head> 的 <title> 标签；品牌尾巴沿用站点里其他页面的写法。"
        return title or None, after, how_to, Confidence.HEURISTIC

    core = _strip_site_suffix(title, [suffix] if suffix else [])
    if code in ("title.too_long", "title.chinese_too_long", "title.pixel_overflow"):
        # 预算内优先保住「页面独有部分」，品牌尾巴让位
        after = _clip(core, budget)
        if suffix and len(after) + 3 + len(suffix) <= budget:
            after = f"{after} - {suffix}"
        how_to = "替换该页 <title>：保留页面主题词前置，站点名放尾部且可省略。"
        return title, after, how_to, Confidence.HEURISTIC

    # title.too_short：把页面主题写完整——补站点名只是兜底，不硬凑字数
    if suffix and suffix not in title:
        after = f"{title} - {suffix}"
    else:
        after = title
    how_to = "title 短了会浪费搜索结果的黄金位置：把「页面主题 + 差异点」写全（如品类、规格、适用场景）。"
    return title, after, how_to, Confidence.HEURISTIC


def _fix_meta(page: Page) -> tuple[str, str, str, Confidence]:
    budget = _META_LIMIT_CJK if _is_cjk_text(page.text[:200]) else _META_LIMIT_LATIN
    after = _first_sentences(page.text, budget)
    if not after:
        # 正文为空（列表页/空壳页）时**不硬编**：没有素材就交人工。
        raise ValueError("no text to draft meta")
    how_to = "替换该页 <meta name=\"description\">；正文首句只是底稿，请润色成一句「这页解决什么问题」。"
    return (page.meta_description or None), after, how_to, Confidence.HEURISTIC


def _fix_h1(page: Page, code: str, suffix: Optional[str]) -> tuple[str, str, str, Confidence]:
    if code == "h1.missing":
        base = _strip_site_suffix((page.title or "").strip(), [suffix] if suffix else [])
        if not base:
            raise ValueError("no title to derive h1")
        how_to = "在正文主标题位置补一个 <h1>：与 title 同义即可，不要再堆第二个关键词。"
        return None, base, how_to, Confidence.HEURISTIC
    # h1.multiple：保留第一个，其余降级 h2——规则文案里就是这么要求的
    first = page.h1[0].strip() if page.h1 else ""
    if not first:
        raise ValueError("no h1")
    how_to = f"该页共 {len(page.h1)} 个 H1：保留第一个，其余改写成 <h2>（层级表达小节，不表达页面主题）。"
    return " | ".join(x.strip() for x in page.h1), first, how_to, Confidence.DETERMINISTIC


def _fix_canonical(page: Page) -> tuple[str, str, str, Confidence]:
    self_url = (page.final_url or page.url).split("#")[0]
    how_to = "在 <head> 加自指 canonical，把带参数/大小写的变体统一到规范地址。"
    return page.canonical or None, self_url, how_to, Confidence.DETERMINISTIC


def _fix_lang(page: Page) -> tuple[str, str, str, Confidence]:
    zh = sum(1 for ch in page.text[:2000] if "\u4e00" <= ch <= "\u9fff")
    after = "zh-CN" if zh * 2 >= max(len(page.text[:2000]), 1) else "en"
    how_to = "给 <html> 加 lang 属性（读屏与搜索引擎都靠它判语言）。多语言站按本页实际语种填。"
    return None, after, how_to, Confidence.HEURISTIC


def _fix_alt(page: Page, code: str) -> list[tuple[str, str, str, str, Confidence]]:
    """逐图给 alt 底稿：从文件名还原可读短语。返回 (field, before, after, how_to, conf)。"""
    out = []
    for img in page.images:
        if code == "img.alt.generic":
            if not img.alt or img.alt.strip().lower() not in {
                "image", "img", "photo", "picture", "图片", "图", "logo", "banner",
            }:
                continue
        elif img.alt and img.alt.strip():
            continue
        name = urlparse(img.src).path.rsplit("/", 1)[-1]
        name = name.rsplit(".", 1)[0]
        draft = " ".join(w for w in name.replace("_", " ").replace("-", " ").split() if w)
        if not draft:
            continue
        out.append((
            f"img_alt:{img.src}",
            img.alt,
            draft,
            "把下面的短语写进该 <img> 的 alt（描述图片内容，不是关键词位）；"
            "纯装饰图请改用 alt=\"\" 而不是编文案。",
            Confidence.HEURISTIC,
        ))
    return out


def _recipe(code: str, field: str, domain: str, pages: list[Page]) -> tuple[str, str]:
    """站点级配方：after 给模板，how_to 说清落地方式。返回 (after, how_to)。"""
    if field == "robots_txt":
        after = (
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            "Sitemap: https://" + domain + "/sitemap.xml\n"
        )
        return after, (
            "在站点根目录提供 /robots.txt。先明确哪些路径**有意**屏蔽收录（后台、结账页），"
            "再照模板写；写完用 Google/Baidu 站长工具的 robots 检测器验一遍。"
        )
    if field == "sitemap":
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "  <url>\n"
            f"    <loc>https://{domain}/</loc>\n"
            "    <lastmod>YYYY-MM-DD</lastmod>\n"
            "  </url>\n"
            "</urlset>\n",
            "生成 sitemap.xml 并在 robots.txt 里声明。URL 必须是规范地址（与 canonical 一致），"
            "只放 200 状态的可索引页；页面多时用 sitemap 索引分片。",
        )
    if field == "jsonld":
        sample_url = pages[0].url if pages else f"https://{domain}/"
        return (
            json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "WebSite",
                    "name": domain,
                    "url": sample_url,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "先从 WebSite / Organization 这类站点级标记做起，再按页面类型补 "
            "Article / Product / FAQPage。用富媒体结果测试工具验字段完整性。",
        )
    if field == "open_graph":
        return (
            '<meta property="og:title" content="（同 title）">\n'
            '<meta property="og:description" content="（同 meta description）">\n'
            '<meta property="og:url" content="（本页规范地址）">\n'
            '<meta property="og:image" content="（1200×630 分享封面图）">',
            "在 <head> 补 Open Graph 四件套，社交分享卡片才有内容可显示；"
            "og:image 指向的图必须可公开访问。",
        )
    if field == "noindex_review":
        return (
            '<meta name="robots" content="index, follow">',
            "先确认这个页面**是不是有意屏蔽收录**（结账页、内部搜索页屏蔽是正确配置，不要改）。"
            "确认是误配再把 noindex 摘掉；确属有意则在工单里标「已知晓」。",
        )
    return "", "见规则详情。"


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def build_fixpack(pages: list[Page], issues: list[Issue], domain: str) -> FixPack:
    """把一次扫描的页面与问题，转成整改工单。

    ⚠️ 站点级问题（title.duplicate / meta.duplicate 等）的 ``Issue.url``
    是 None，处方要按「页面集合」重新归因到具体页面——报告可以说
    「N 个页面重复」，工单必须落到「哪个页面改成什么」。
    """
    by_url = {p.url: p for p in pages}
    suffix = _detect_site_suffix(pages)
    pack = FixPack(domain=domain, pages_considered=len(pages))

    def add(page: Optional[Page], code: str, field: str, before: Optional[str],
            after: str, how_to: str, confidence: Confidence) -> None:
        pack.actions.append(FixAction(
            url=page.url if page else None,
            code=code, field=field, before=before, after=after,
            how_to=how_to, confidence=confidence,
        ))

    for issue in issues:
        code = issue.code
        page = by_url.get(issue.url) if issue.url else None

        # --- 站点级：重复 title / 重复 meta，按页面集合逐页归因 ---
        if code in ("title.duplicate", "meta.duplicate"):
            from collections import defaultdict

            groups: dict[str, list[Page]] = defaultdict(list)
            key = "title" if code == "title.duplicate" else "meta_description"
            for p in pages:
                val = (p.title if key == "title" else p.meta_description) or ""
                if val.strip():
                    groups[val.strip()].append(p)
            n = 0
            for val, group in groups.items():
                if len(group) < 2:
                    continue
                for p in group:
                    try:
                        if key == "title":
                            core = _strip_site_suffix(val, [suffix] if suffix else [])
                            # 差异化因子：优先页面自己的 H1（它本来就是页面主题的正面证据）
                            diff = _strip_site_suffix(p.h1[0], [suffix] if suffix else []) if p.h1 else ""
                            after = diff if diff and diff != core else _clip(val + " · " + urlparse(p.url).path.strip("/").replace("/", " · "), _title_budget(p))
                            how_to = "该 title 与站内其他页面完全相同：把页面主题词（如 H1）换进去做区分。"
                            add(p, code, "title", val, after, how_to, Confidence.HEURISTIC)
                        else:
                            _, after, how_to, conf = _fix_meta(p)
                            add(p, code, "meta_description", val, after, how_to, conf)
                        n += 1
                    except ValueError:
                        continue
            if n == 0:
                pack.notes.append(f"{code} 命中了，但没有页面能安全自动改写——已全部转人工。")
            continue

        if code in _RECIPE_CODES and page is None:
            field = _RECIPE_CODES[code]
            after, how_to = _recipe(code, field, domain, pages)
            # 配方类没有「改前」字段值可言（它不是替换某个标签），
            # 把 fix_example 当 before 展示会误导成「现状是这样」。
            add(None, code, field, None, after, how_to, Confidence.RECIPE)
            continue

        if page is None or code not in _PAGE_FIELD_CODE:
            pack.manual_review.append(issue)
            continue

        field = _PAGE_FIELD_CODE[code]
        try:
            if field == "title":
                before, after, how_to, conf = _fix_title(page, code, suffix)
                add(page, code, field, before, after, how_to, conf)
            elif field == "meta_description":
                before, after, how_to, conf = _fix_meta(page)
                add(page, code, field, before, after, how_to, conf)
            elif field == "h1":
                before, after, how_to, conf = _fix_h1(page, code, suffix)
                add(page, code, field, before, after, how_to, conf)
            elif field == "canonical":
                before, after, how_to, conf = _fix_canonical(page)
                add(page, code, field, before, after, how_to, conf)
            elif field == "html_lang":
                before, after, how_to, conf = _fix_lang(page)
                add(page, code, field, before, after, how_to, conf)
            elif field == "viewport":
                add(page, code, field, page.viewport, _VIEWPORT,
                    "在 <head> 加标准响应式 viewport；已有 viewport 但配置怪异的换用这行。",
                    Confidence.DETERMINISTIC)
            elif field == "img_alt":
                rows = _fix_alt(page, code)
                if not rows:
                    raise ValueError("no image needs alt")
                for f, before, after, how_to, conf in rows:
                    add(page, code, f, before, after, how_to, conf)
        except ValueError as exc:
            # 素材不足（空页、正文抽不出来）→ 转人工，理由写进工单
            pack.manual_review.append(issue)
            pack.notes.append(f"{code} @ {page.url}：{exc}，无法安全起草，转人工。")
            continue

    # 按严重度 + 字段排序：工单是拿来分派的，得先看大头
    sev_rank = {s: i for i, s in enumerate(Severity)}
    pack.actions.sort(key=lambda a: (sev_rank.get(_code_severity(a.code), 9), a.field, a.url or ""))
    if not pack.actions and not pack.manual_review:
        pack.notes.append("没有可自动开出处方的问题——本次扫描的命中项都需要人工判断或无需改动。")
    pack.notes.append(
        f"品牌尾巴识别：{'「' + suffix + '」' if suffix else '未识别到'}"
        + ("（改写会沿用这个写法）" if suffix else "（title 改写不加站点名后缀）")
    )
    return pack


_CODE_SEVERITY: dict[str, Severity] = {}


def _code_severity(code: str) -> Optional[Severity]:
    """code → 严重度。从规则注册表取，避免处方层手抄一份会漂移的清单。"""
    if not _CODE_SEVERITY:
        from .audit.engine import default_registry
        from .models import Market

        reg = default_registry()
        for r in reg.page_rules_for(list(Market)) + reg.site_rules_for(list(Market)):
            _CODE_SEVERITY[r.code] = r.severity
    return _CODE_SEVERITY.get(code)


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------


def _brand_line(brand: Optional[str]) -> str:
    return f"本工单由 **{brand}** 出具。" if brand else "工单由 SEO-Claw 生成。"


def render_fixpack_markdown(pack: FixPack, *, brand: Optional[str] = None) -> str:
    """整改工单（Markdown）：按「改前 → 改后」组织，可直接贴进工单系统。"""
    lines: list[str] = [
        f"# SEO 整改工单 · {pack.domain}",
        "",
        _brand_line(brand),
        "",
        f"生成时间：{pack.generated_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"审过页面 {pack.pages_considered} 页 · 处方 {len(pack.actions)} 条 · "
        f"转人工 {len(pack.manual_review)} 条",
        "",
    ]
    det = pack.by_confidence
    lines += [
        "## 可信度分档（先看这行再动手）",
        "",
        f"- ✅ **可直接照抄**：{len(det[Confidence.DETERMINISTIC])} 条",
        f"- ✍️ **机器起草，发布前人工润色**：{len(det[Confidence.HEURISTIC])} 条",
        f"- 🧩 **配方（需结合站点结构落地）**：{len(det[Confidence.RECIPE])} 条",
        "",
    ]
    if pack.notes:
        lines += ["## 工单说明", ""]
        lines += [f"- {n}" for n in pack.notes]
        lines.append("")

    if pack.actions:
        lines += ["## 处方明细", ""]
        for i, a in enumerate(pack.actions, 1):
            where = a.url or "（站点级）"
            lines += [
                f"### {i}. `{a.field}` · {where}",
                "",
                f"- 触发规则：`{a.code}`"
                + (f" · 波及 {a.pages_affected} 页" if a.pages_affected > 1 else ""),
                f"- 可信度：{CONFIDENCE_LABEL[a.confidence]}",
            ]
            if a.before:
                lines.append(f"- 改前：`{_inline(a.before)}`")
            lines += [
                "- 改后：",
                "",
                "```",
                a.after,
                "```",
                "",
                f"**怎么落地**：{a.how_to}",
                "",
            ]

    if pack.manual_review:
        lines += ["## 转人工（工具不代改）", ""]
        for issue in pack.manual_review:
            lines.append(
                f"- **{issue.severity.value.upper()}** `{issue.code}` "
                f"{issue.title}"
                + (f" @ {issue.url}" if issue.url else "")
            )
            if issue.fix_hint:
                lines.append(f"  - 怎么修：{issue.fix_hint}")
        lines.append("")

    return "\n".join(lines)


def _inline(text: str) -> str:
    return text.replace("`", "'").replace("\n", " ⏎ ")[:160]


def render_fixpack_json(pack: FixPack, *, brand: Optional[str] = None) -> str:
    payload = pack.model_dump(mode="json")
    payload["brand"] = brand
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_fixpack_csv(pack: FixPack) -> str:
    """一行一个处方：给批量派工 / Excel 透视用。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["url", "field", "code", "confidence", "before", "after", "how_to"])
    for a in pack.actions:
        w.writerow([a.url or "", a.field, a.code, a.confidence.value,
                    a.before or "", a.after, a.how_to])
    return buf.getvalue()


def render_fixpack_diff(pack: FixPack) -> str:
    """unified-diff 风格的逐页改动稿：前端/CMS 工程师可直接照着改模板。

    diff 的「原文件」是该页 head 字段的现状快照，不是完整 HTML——
    工具没有站点源码，编不出真 patch，这是它的诚实边界。
    """
    import difflib

    out: list[str] = []
    by_url: dict[str, list[FixAction]] = {}
    for a in pack.actions:
        if a.url and a.field != "img_alt":
            by_url.setdefault(a.url, []).append(a)

    for url, actions in by_url.items():
        before_lines = [f'{a.field}: {a.before if a.before is not None else "(缺失)"}' for a in actions]
        after_lines = [f"{a.field}: {a.after}" for a in actions]
        diff = difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{url}", tofile=f"b/{url}", lineterm="",
        )
        out.append("\n".join(diff))
    return "\n\n".join(out) + ("\n" if out else "")


RENDERERS = {
    "md": render_fixpack_markdown,
    "json": render_fixpack_json,
    "csv": lambda pack, **kw: render_fixpack_csv(pack),
    "diff": lambda pack, **kw: render_fixpack_diff(pack),
}


def render_fixpack(pack: FixPack, fmt: str, *, brand: Optional[str] = None) -> str:
    """按格式渲染工单。fmt: md / json / csv / diff。"""
    try:
        fn = RENDERERS[fmt]
    except KeyError:
        raise ValueError(f"未知的工单格式：{fmt}（可选 md / json / csv / diff）") from None
    return fn(pack, brand=brand)
