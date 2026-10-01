"""Google 生态专属检查项。

为什么要有这个包
----------------
BASE 包里的规则是「哪个搜索引擎都这么认为」的。但 Google 有自己的一套
判罚逻辑：移动端优先（没有 viewport 视同自断双腿）、`<html lang>` 是
语言定向和 hreflang 的地基、搜索结果的 title 是按**像素宽度**而不是
字符数截断的。这些规则在百度/微信生态里权重完全不同，所以单独分包，
`market = Market.GOOGLE`。

选规则的标准（宁可少报也不要误报）
----------------------------------
本包只收**能从 Page 上直接验证**的规则。四个候选最终被砍掉，理由写
在「未实现」一节里——工具的信誉是靠不误报攒出来的，一条乱报的规则
足以让用户不再相信剩下 20 条。

另一条硬规矩：凡是靠「我没看到 X」下结论的规则，必须先用
`ctx.has_enough_data()` 确认覆盖率够。本包保留的两条 SITE 级信号
都遵守这一条。
"""

from __future__ import annotations

from typing import Iterable

from ....models import Issue, Market, Page, Scope, Severity
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()


# --------------------------------------------------------------------------
# 1. lang.missing —— <html> 没有 lang 属性
# --------------------------------------------------------------------------


@reg.register
class HtmlLangMissing(Rule):
    code = "lang.missing"
    market = Market.GOOGLE
    severity = Severity.HIGH
    title = "<html> 标签缺少 lang 属性"
    description = (
        "lang 告诉 Google「这个页面是什么语言」。它是屏幕阅读器朗读发音的"
        "依据，也是 Google 判断「搜索结果该给哪国用户」以及 hreflang 配对"
        "正确与否的前提。缺失时，Google 只能靠正文猜，猜错就会把页面推给"
        "看不懂的用户，CTR 直接掉。"
    )
    fix_hint = '在 <html> 上加 lang 属性，取页面**主要内容**的语言 BCP 47 代码（如 zh-CN、en-US）。'
    fix_example = '<html lang="zh-CN">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200:
            return
        # 空字符串同样是有害的：<html lang=""> 说明作者写了但没填
        lang = (page.lang or "").strip()
        if lang:
            return
        yield self._issue(
            page,
            {
                "html_lang_found": False,
                "html_lang_raw": page.lang,
                "detected_from_text": _guess_text_lang(page.text),
                "content_sample": page.text[:80],
                "note": "lang 缺失是硬证据：解析器读了 <html> 的 lang 属性，"
                "确认它为空或不存在，不存在「没抓到」的问题",
            },
        )


# --------------------------------------------------------------------------
# 2. lang.not_html_lang —— 声明的语言和实际内容对不上
# --------------------------------------------------------------------------


@reg.register
class HtmlLangMismatch(Rule):
    code = "lang.not_html_lang"
    market = Market.GOOGLE
    severity = Severity.MEDIUM
    title = "html lang 声明的语言与正文实际语言不符"
    description = (
        "lang 写错比不写更隐蔽：它让 Google 把页面定向给错误的语言人群，"
        "语音搜索、TOC 结果、以及 hreflang 配对都会跟着出错。"
        "常见成因是多语言站改版时只翻了模板没翻 head，或 CMS 默认写死 en。"
    )
    fix_hint = (
        "把 lang 改成正文的实际语言；如果这一页确实是多语混排，"
        "说明主语言是什么（通常取占比最高的那一种）。"
    )
    fix_example = '<html lang="zh-CN">  <!-- 正文是中文，lang 却是 en 就改这里 -->'

    # 声明语言 → 期望的书写体系
    _CJK_LANGS = {"zh", "ja", "ko", "yue", "cmn", "wuu", "hak", "nan"}
    _LATIN_LANGS = {
        "en", "fr", "de", "es", "it", "pt", "nl", "sv", "da", "no", "nb",
        "fn", "fi", "pl", "cs", "ro", "hu", "tr", "id", "vi", "ca", "gl",
        "eu", "af", "sq", "is", "ms", "tl", "et", "lv", "lt", "sk", "sl",
        "cy", "ga", "la", "eo", "sw", "fil",
    }

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200:
            return
        lang = (page.lang or "").strip().lower()
        if not lang or lang in ("x-default", "und"):
            return
        primary = lang.replace("_", "-").split("-")[0]
        if primary in self._CJK_LANGS:
            expected = "cjk"
        elif primary in self._LATIN_LANGS:
            expected = "latin"
        else:
            # 阿拉伯语/希伯来语/西里尔/泰文/天城文等一律不判。
            # 只比对两种书写体系，是为了把误报率压到可接受范围。
            return

        cjk, latin = _script_counts(page.text)
        # 样本太小时不做比例判断——几行导航栏的字符分布不代表整页
        if cjk + latin < 100:
            return

        if expected == "latin" and cjk > latin:
            verdict, actual = "declared_latin_but_content_cjk", "cjk"
        elif expected == "cjk" and latin > cjk * 2:
            verdict, actual = "declared_cjk_but_content_latin", "latin"
        else:
            return

        yield self._issue(
            page,
            {
                "html_lang": page.lang,
                "expected_script": expected,
                "actual_script": actual,
                "cjk_chars": cjk,
                "latin_chars": latin,
                "sampled_chars": cjk + latin,
                "content_sample": page.text[:100],
                # 混合语页面是合法的，工具无法自动区分，只能给信号
                "verdict": "likely_wrong_or_untranslated",
                "verdict_explain": (
                    "正文字符体系与 lang 声明明显不符，大概率是 lang 没跟着内容更新；"
                    "⚠️ 若该页确实是中英混排的落地页，可能是有意为之——请人工确认。"
                ),
            },
        )


# --------------------------------------------------------------------------
# 3. viewport.missing —— 移动端优先，没有响应式视口
# --------------------------------------------------------------------------


@reg.register
class ViewportMissing(Rule):
    code = "viewport.missing"
    market = Market.GOOGLE
    severity = Severity.HIGH
    title = "页面没有 viewport，移动端会被按桌面版渲染"
    description = (
        "Google 的索引和排名完全以**移动端版本**为准（mobile-first indexing）。"
        "没有 viewport 的页面在手机上会被缩成一张看不清字的小图，"
        "用户直接往回退，CTR 崩掉；同时这条页面在移动端索引里会拿到"
        "「不适合移动设备」的降权标记。这是 Google 生态里性价比最高的一个修复。"
    )
    fix_hint = '在 <head> 里加 viewport meta，务必带上 width=device-width 和 initial-scale=1。'
    fix_example = '<meta name="viewport" content="width=device-width, initial-scale=1">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200:
            return
        viewport = (page.viewport or "").strip()
        if viewport:
            return
        yield self._issue(
            page,
            {
                "viewport_found": False,
                "content_type": page.content_type,
                "note": "解析器在 <head> 里找过 <meta name=\"viewport\">，确认不存在",
                "mobile_first_indexing": "Google 自 2019 年起以移动端版本为准索引全站",
            },
        )


# --------------------------------------------------------------------------
# 4. viewport.not_responsive —— 有 viewport，但没用 device-width
# --------------------------------------------------------------------------


@reg.register
class ViewportNotResponsive(Rule):
    code = "viewport.not_responsive"
    market = Market.GOOGLE
    severity = Severity.MEDIUM
    title = "viewport 配置妨碍移动端可读性（需确认是否有意为之）"
    description = (
        "两种情况：一是用固定像素宽度（如 width=980）或只写 initial-scale，"
        "手机浏览器会按指定宽度渲染再整体缩放，文字被压得极小；"
        "二是 user-scalable=no 禁止用户手动放大，属于无障碍合规问题，"
        "移动端排名上也可能被降权。"
        "⚠️ 工具无法区分「忘了改」与「这就是个桌面端后台/内嵌页」——"
        "请确认这一页是否面向手机用户。"
    )
    fix_hint = (
        "面向手机用户的页面改成 width=device-width, initial-scale=1，"
        "并去掉 user-scalable=no；确实只在桌面端打开的页面可忽略本条。"
    )
    fix_example = '<meta name="viewport" content="width=device-width, initial-scale=1">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200:
            return
        viewport = (page.viewport or "").strip()
        if not viewport:
            return  # 已由 viewport.missing 覆盖，不重复报
        low = viewport.lower().replace(" ", "")
        has_device_width = "device-width" in low
        no_zoom = "user-scalable=no" in low
        # 两个问题各自独立：user-scalable=no 就算配了 device-width 也依然有害，
        # 不能因为「宽度写对了」就把禁缩放这个无障碍缺陷一起放过去。
        if has_device_width and not no_zoom:
            return
        problems = []
        if not has_device_width:
            problems.append("missing_device_width")
        if no_zoom:
            problems.append("user_scalable_no")
        yield self._issue(
            page,
            {
                "viewport": viewport,
                "problems": problems,
                "has_device_width": has_device_width,
                "has_initial_scale": "initial-scale" in low,
                "has_user_scalable_no": no_zoom,
                "note": "user-scalable=no 禁止用户手动放大，是无障碍问题，"
                "移动端排名上也可能被降权",
                "verdict": "possibly_intentional",
                "verdict_explain": (
                    "固定宽度视口常见于桌面后台和内嵌页；"
                    "⚠️ 面向手机用户的页面则一定是 bug，请人工确认。"
                ),
            },
        )


# --------------------------------------------------------------------------
# 5. title.pixel_overflow —— title 按像素超宽被截断
# --------------------------------------------------------------------------


@reg.register
class TitlePixelOverflow(Rule):
    code = "title.pixel_overflow"
    market = Market.GOOGLE
    severity = Severity.MEDIUM
    title = "title 估算像素宽度超出搜索结果截断阈值"
    description = (
        "Google 搜索结果的 title 是**按像素宽度**截断的（约 580px），"
        "不是按字符数。所以 30 个中文（≈480px）不截断，"
        "而 62 个小写英文字母（约 500px）却可能刚好越界。"
        "BASE 包的 title.too_long 只看字符数，看不出这类溢出。"
    )
    fix_hint = (
        "把最核心的词前置到前 25 个字符内。中文 title 控制在 30 字以内、"
        "英文控制在 55 字符以内，留出品牌后缀的余量。"
    )
    fix_example = '"登山鞋 男款 防水防滑 - 品牌名"   # 15 字 ≈ 240px，安全区'

    # 桌面端搜索结果标题的经验截断宽度
    _THRESHOLD_PX = 580.0

    # 估算表的**最大**误差幅度（见 _estimate_title_px 的注释），对应标题
    # **完全由字体决定宽度**的字符（拉丁字母、空格、标点、emoji）。
    # 像素估算不是测量值：结论只有在「估值的下界仍然越界」时才可靠，否则
    # 报的只是估算误差本身。
    #
    # 为什么不直接减一个固定的 10%：误差来源**因字符而异**。汉字/假名/谚文
    # 的字宽就是 1em（确定性），估算误差≈0；真正不确定的是拉丁字母和空格，
    # 它们的字宽随字体和抗锯齿变化。所以误差带按「字宽随字体而变的字符占比」
    # 缩放（见 _estimate_title_px 的 variable_share）。
    #   - 37 个汉字 = 592px：字宽确定，误差带 0 → 越过 580px 就是事实 → 必报
    #   - golf.com 583.9px：全是拉丁字母，误差带 10% → 下界 525.5px < 580px，
    #     超出量（3.9px，0.7%）完全落在估算误差里，结论不可靠 → 闭嘴
    # 真实样本见 reports/ 里的 2026 回源核对记录。
    _MAX_ESTIMATE_ERROR = 0.10

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        title = page.title
        if page.status_code != 200 or not title:
            return
        est = _estimate_title_px(title)
        # 误差带随「字宽不确定的字符占比」缩放
        band = self._MAX_ESTIMATE_ERROR * est["variable_share"]
        # 只在误差带下界仍超出阈值时才报——避免把估算误差当成发现
        if est["estimated_px"] * (1.0 - band) <= self._THRESHOLD_PX:
            return
        yield self._issue(
            page,
            {
                "title": title[:120],
                "title_length": len(title),
                "estimated_px": round(est["estimated_px"], 1),
                "threshold_px": self._THRESHOLD_PX,
                "overflow_px": round(est["estimated_px"] - self._THRESHOLD_PX, 1),
                "estimate_error_band": round(band, 4),
                "low_bound_px": round(est["estimated_px"] * (1.0 - band), 1),
                "cjk_chars": est["cjk"],
                "latin_chars": est["latin"],
                "space_chars": est["space"],
                "other_chars": est["other"],
                "emoji_chars": est["emoji"],
                "verdict": "likely_truncated",
                "verdict_explain": (
                    "按 16px 基准字体的字符宽度表估算得出。"
                    "⚠️ 像素估算是近似值（Google 用可变字体，实际字宽随字符而异），"
                    "本条用于筛出「明显超标」的 title，请在搜索结果里目视确认一下。"
                ),
            },
        )


# --------------------------------------------------------------------------
# 未实现的候选规则及原因
# --------------------------------------------------------------------------
#
# hreflang.missing / hreflang.invalid_return
#   Page 模型里没有 hreflang 字段，extract 阶段也没抓 <link rel="alternate"
#   的 hreflang/href。要判断「有 x-default 或多语言变体但缺 hreflang」，
#   必须先在 head 里**正面看到** hreflang 声明才能做「缺失」判断——
#   而我们目前根本拿不到这个数据源。与其写一条永远沉默（或靠猜触发）
#   的规则，不如等 extract 补上 hreflang 采集再实现。
#   hreflang.invalid_return 同理：需要 hreflang 目标 URL + 其状态码，
#   属于「回访校验」类信号（类似 canonical_target_status），要等爬虫侧先有。
#
# amp.missing_on_mobile_article
#   两个原因。(1) 数据上：Page 里没有 AMP 标记（rel=amp / amphtml link /
#   ⚡script）的采集位，判不了「有没有 AMP」。(2) 更根本的是：Google 自 2021 年
#   起已把 AMP 从排名加分项里拿掉，官方说法是「改善核心网页指标比做 AMP 更重要」。
#   在今天还把「没做 AMP」报成问题，是在给用户一条过期且有害的建议。
#
# cwv.lcp_element_missing
#   LCP 元素要靠真实渲染（PerformanceObserver / CrUX 现场数据）才能确定。
#   静态 HTML 只能看到 <img> 列表，看不到「哪张图最终被渲染成 LCP」，
#   也看不到 CSS background-image 和懒加载生效结果。
#   用「第一张图」或「图片没有 width/height」去近似 LCP 是伪科学，
#   报出来的必然是猜测，违反本包「证据必须可自证」的原则。
#   正确的做法是接 CrUX/PageSpeed API 拿真实数据，而不是猜。
#
# pagination.rel_prev_next_missing
#   两层问题。(1) 数据上：rel=prev/next 同样没被采集。
#   (2) 更根本的：Google 在 2019 年正式宣布 rel=prev/next 不再作为抓取信号，
#      连续性完全由 内链 + 锚文本 承担。Google 官方博客明确表示不再使用它。
#      报这条等于教用户去加一个 Google 自己都不读的属性。
#      （若需要「分页页应指向自己 canonical」这类真问题，应归到 canonical 包，
#        且必须先能识别出这是分页页——URL 形态只是线索，不能直接当结论。）
# --------------------------------------------------------------------------
# 维护提示：上面任何一条要启用，先补 Page 字段 + extract 采集 + 测试，
# 再把代码从「未实现」挪到上面，并补上正反两个方向的用例。
# 只改规则文件会让证据字段对不上真实数据源。
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------


def _is_cjk(ch: str) -> bool:
    """CJK 统一表意文字 / 假名 / 谚文 / 全角标点。"""
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x3040 <= cp <= 0x30FF  # 假名
        or 0xAC00 <= cp <= 0xD7AF  # 谚文
        or 0x3000 <= cp <= 0x303F  # CJK 标点
        or 0xFF00 <= cp <= 0xFF60  # 全角形式
        or 0xF900 <= cp <= 0xFAFF
    )


def _is_latin(ch: str) -> bool:
    """拉丁字母（含带变音符的扩展区）。"""
    if ch.isalpha():
        cp = ord(ch)
        if cp < 0x0250:  # 基本拉丁 + 拉丁扩展 A/B
            return True
    return False


def _script_counts(text: str) -> tuple[int, int]:
    """统计正文里 CJK 与拉丁字母的字符数。"""
    cjk = latin = 0
    for ch in text:
        if _is_cjk(ch):
            cjk += 1
        elif _is_latin(ch):
            latin += 1
    return cjk, latin


def _guess_text_lang(text: str) -> str:
    """粗判正文语言，只用于给 lang.missing 提供「该填什么」的提示。"""
    cjk, latin = _script_counts(text)
    if cjk == 0 and latin == 0:
        return "unknown"
    if cjk > latin * 2:
        return "cjk"
    if latin > cjk * 2:
        return "latin"
    return "mixed"


# 字符宽度表（相对 16px 基准字体，单位 px）。取值来自常见无衬线 UI 字体
# 的平均字宽，误差在 ±10% 以内——足够区分「明显超标」和「安全区」，
# 不追求像素级精确（Google 用的是可变字体，本来也算不出来）。
_W_NARROW = set("iljItf.,;:'!|()[]-·’‘“”\"`")  # ≈4.5px
_W_UPPER = 10.7
_W_LOWER = 8.0
_W_DIGIT = 8.9
_W_SPACE = 4.4
_W_PUNCT = 5.5
_W_OTHER_ALPHA = 9.0  # 西里尔、希腊等
_W_EMOJI = 16.0  # emoji 按 1em 全宽渲染，当成标点算会窄一半

# 中英文弯引号。ASCII 的 ' " 确实窄，但 “”‘’ 在 CJK 字体里是全角
# （=1em）。按 4.5px 算会低估约 3.5px/个（真实样本：discourse 的中文标题）。
_W_CURLY_QUOTES = set("“”‘’")
_W_CURLY_QUOTES_NARROW = 4.5
_W_CURLY_QUOTES_FULL = 16.0


def _is_emoji(ch: str) -> bool:
    """emoji / 符号类区块。这些字符实际渲染都接近全角。"""
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF  # 各类 pictograph、emoji
        or 0x2600 <= cp <= 0x27BF  # 杂项符号、装饰符号（✓★❤…）
        or 0x2B00 <= cp <= 0x2BFF  # 补充箭头/星号
        or 0x1F1E6 <= cp <= 0x1F1FF  # 区域指示符（国旗）
    )


def _is_emoji_modifier(ch: str) -> bool:
    """变体选择符 / ZWJ：只影响相邻 glyph 形状，本身不占宽度。"""
    cp = ord(ch)
    return cp == 0x200D or 0xFE00 <= cp <= 0xFE0F


def _estimate_title_px(title: str) -> dict[str, int | float]:
    """估算 title 在搜索结果里的渲染宽度（px）。

    纯确定性计算：同样的字符串永远得到同样的结果，不依赖字体环境。
    """
    total = 0.0
    cjk = latin = space = other = emoji = 0
    # variable = 字宽随字体而变（估算有误差）的字符数。汉字/假名/谚文是 1em
    # 定宽，计入它只会虚增误差带，把本来确定的越界结论也一并抹掉。
    variable = 0
    # 弯引号按全角还是窄，取决于这句 title 是不是 CJK 排版的——
    # 中文标题里的 “” 就是全角，英文标题里的 ' 是窄的。
    curly_w = _W_CURLY_QUOTES_FULL if any(_is_cjk(ch) for ch in title) else _W_CURLY_QUOTES_NARROW
    for ch in title:
        if _is_emoji_modifier(ch):
            continue
        if _is_emoji(ch):
            total += _W_EMOJI
            emoji += 1
            variable += 1
        elif _is_cjk(ch):
            # CJK 是全角，等于一个 em（定宽，不计入误差）
            total += 16.0
            cjk += 1
        elif ch in _W_CURLY_QUOTES:
            total += curly_w
            latin += 1
            variable += 1
        elif ch.isspace():
            total += _W_SPACE
            space += 1
            variable += 1
        elif ch in _W_NARROW:
            total += 4.5
            latin += 1
            variable += 1
        elif ch.isdigit():
            total += _W_DIGIT
            other += 1
            variable += 1
        elif _is_latin(ch):
            total += _W_UPPER if ch.isupper() else _W_LOWER
            latin += 1
            variable += 1
        elif ch.isalpha():
            total += _W_OTHER_ALPHA
            other += 1
            variable += 1
        else:
            total += _W_PUNCT
            other += 1
            variable += 1
    counted = cjk + latin + space + other + emoji
    return {
        "estimated_px": total,
        "cjk": cjk,
        "latin": latin,
        "space": space,
        "other": other,
        "emoji": emoji,
        # 字宽随字体而变的字符占比 ∈ [0,1]；它决定估算有多大不确定性
        "variable_share": (variable / counted) if counted else 0.0,
    }
