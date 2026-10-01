"""基础检查项包：所有市场通用。"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

from ....models import Issue, Market, Page, Scope, Severity
from ....util import normalize_url, same_url_ignoring_path_case
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()


@reg.register
class TitleMissing(Rule):
    code = "title.missing"
    severity = Severity.CRITICAL
    title = "页面缺少 title 标签"
    description = "title 是搜索结果里最重要的可点击文案。缺失时搜索引擎会自行从页面内容里截取，排名与点击率都会受损。"
    fix_hint = "在 <head> 里加一个 <title>，写成「核心关键词 - 品牌名」的结构。"
    fix_example = "<head>\n  <title>防水登山鞋 男款防滑 - 品牌名</title>\n</head>"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ⚠️ 「静态 HTML 里没找到 title」推不出「这个页面没有 title」。
        #
        # 实测 www.agoda.com：初始 HTML 有 737KB，但**整份文档里根本没有
        # <title> 标签**（curl -sL 后 grep -c '<title' 命中 0 次），
        # title 是客户端 JS 注入的。提取层静态解析拿不到 → 旧版报
        # CRITICAL「页面缺少 title」，用户会照着去改一个明明有 title 的首页。
        #
        # 这和 noindex.present、Soft404 是同一个错误：把「我没看见」当成
        # 「它不存在」。判据必须是**正面证据**，而提取层已经把那个证据算好了：
        # likely_js_rendered（在 _looks_js_rendered_shell 里量测 HTML 体积、
        # 框架指令特征、挂载点得出，不是猜的）。agoda 实测该标记为 True。
        #
        # 判对的场景一条没少：非 JS 渲染页面缺 title 照报，因为那时候
        # 「静态 HTML 里没有」就等于「浏览器里也没有」。
        if page.likely_js_rendered:
            return
        if page.status_code == 200 and not page.title:
            yield self._issue(page, {"html_title_found": False})


@reg.register
class TitleTooLong(Rule):
    code = "title.too_long"
    severity = Severity.MEDIUM
    title = "title 过长会被截断"
    description = "title 超出显示长度时会被搜索结果截断，关键信息放不进去就白写了。中文建议 ≤30 字，英文建议 ≤60 字符。"
    fix_hint = "把最重要的关键词前置，删掉形容词和冗余修饰。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        limit = 30 if _is_cjk(page.title or "") else 60
        if limit == 30 and len(page.title or "") > 30:
            yield self._issue(
                page,
                {"title": page.title, "length": page.title_length, "limit": limit},
            )
        elif limit == 60 and page.title_length > 60:
            yield self._issue(
                page,
                {"title": page.title, "length": page.title_length, "limit": limit},
            )


@reg.register
class TitleTooShort(Rule):
    code = "title.too_short"
    severity = Severity.LOW
    title = "title 过短，浪费了黄金位置"
    description = (
        "过短的 title 通常意味着没覆盖到用户搜索的关键词，浪费搜索结果里最显眼的位置。\n"
        "⚠️ 例外：站名/人名本身就是完整名称（如「Julia Evans」），或站点是单页应用时，"
        "短 title 是正常选择，不要为了凑长度硬塞关键词。"
    )
    fix_hint = "补充用户真实会用到的搜索词，保持自然可读。"

    # 常见功能词：出现在 title 里说明它是描述句，不是站名/品牌名
    _FUNCTION_WORDS = frozenset(
        """a an the of for to in on and or with from at by is are be your our
        my we it this that how what why guide best top free get""".split()
    )

    @classmethod
    def _looks_like_proper_name(cls, title: str) -> bool:
        """判断短 title 是否其实是站名/人名/品牌名。

        判据：词数少（<=3）且每个词都是首字母大写的专有名词、不含功能词。
        实测 jvns.ca 的 "Julia Evans" 属此类——报「过短」等于让用户去堆关键词，
        而站名本身就是完整品牌，硬塞关键词反而降低点击率。
        """
        words = [w for w in title.split() if w]
        if not words or len(words) > 3:
            return False
        if any(w.lower() in cls._FUNCTION_WORDS for w in words):
            return False
        # 每个词都要求首字母大写（容忍全大写缩写）
        return all(w[:1].isupper() or w.isupper() for w in words if w[:1].isalpha())

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.title or not (0 < page.title_length < 15):
            return
        title = page.title.strip()
        # ⚠️ 占位符豁免的判定**必须排在 proper-name 豁免之前**，否则形同虚设。
        # 「Home」「Index」「Document」「Untitled」都是单词首字母大写、
        # 不含功能词的短词，_looks_like_proper_name 一律放它们过关
        # （实测 'Home' → proper_name=True），占位符检查永远轮不到执行。
        # 而这些词恰恰是**没改完的模板默认值**：既没品牌也没关键词，
        # 用户看到这条会去改一个本来就该改的东西——是真问题，不该放过。
        # 品牌名（Apple、Nike 这类真单词）不在 _PLACEHOLDER_TITLES 里，
        # 照旧按 proper-name 豁免，放宽范围严格限定在这十几个别名上。
        if title.lower() in self._PLACEHOLDER_TITLES:
            pass  # 落到下面照报
        elif self._looks_like_proper_name(title):
            return
        # 功能性页面的短 title 是**正确答案**，不该参与「黄金位」评估
        elif self._is_functional_page(page):
            return
        yield self._issue(
            page, {"title": page.title, "length": page.title_length, "min": 15}
        )

    # ── 功能性页面判定 ──────────────────────────────────────────
    #
    # ⚠️ 这条规则的立论是「title 是搜索结果里最显眼的位置，写短了等于浪费」。
    # 但这个前提**只对「要参与关键词竞争的内容页」成立**。对功能性页面，
    # title 是一枚标签，不是广告位，写短恰恰是对的。
    #
    # 实测三个样本，全部按旧逻辑误报：
    #   www.gov.sg/            title='Home | gov.sg'    13 字 → 首页
    #   indiehackers.com/login title='Sign in'          7 字 → 登录页
    #     （实测 302 到 /sign-in，`Sign in` 正是登录页的规范写法）
    #
    # 要求作者给登录页起一个 15 字以上的标题，等于让用户去改本来正确的东西：
    # 用户收到这条会去干嘛？把「Sign in」改成「Sign in - Welcome Back to
    # Indie Hackers」，纯粹为了迎合尺子，搜索结果反而更差。
    #
    # ⚠️ 判据必须落在 **URL 形态**上，不能靠 title 字面猜。
    # 「Home | gov.sg」里没有 home/首页之外的线索，纯字面规则要么漏、要么
    # 误伤真的内容页。URL 是页面角色的客观事实，title 只是结果。
    _FUNCTIONAL_PATH_SEGMENTS = frozenset({
        # 登录/认证
        "login", "logout", "signin", "sign-in", "sign_in", "auth",
        "authenticate", "sso", "session",
        # 法律与无障碍声明
        "accessibility", "accessibility-statement", "web-accessibility-statement",
        "privacy", "privacy-policy", "terms", "terms-of-use", "legal",
        "disclaimer", "cookies", "cookie-policy", "imprint", "notices",
    })

    # 这些 title 无论出现在哪种页面上都是**真问题**：它们既没品牌也没关键词，
    # 是没改完的默认占位符。所以功能性页面的豁免不覆盖它们。
    _PLACEHOLDER_TITLES = frozenset({
        "home", "index", "page", "default", "untitled", "document", "loading",
        "welcome", "test", "none", "null", "todo", "new page", "site",
        "首页", "主页", "文档", "未命名", "默认",
    })

    @classmethod
    def _is_functional_page(cls, page: Page) -> bool:
        """按 URL 形态判断这是不是「title 本来就该短」的功能性页面。"""
        path = (urlsplit(page.final_url or page.url or "").path or "/").lower()
        segments = [s for s in path.split("/") if s]
        # 首页：站点根路径
        if not segments:
            return True
        return any(s in cls._FUNCTIONAL_PATH_SEGMENTS for s in segments)


@reg.register
class TitleDuplicate(Rule):
    code = "title.duplicate"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "多个页面 title 完全相同"
    description = "重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。"
    fix_hint = "为每个页面写能体现其独特价值的 title，用页面主题词区分。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 不需要覆盖率门槛：重复 title 是「正面证据」——看到两个页面
        # title 相同就能确认，与抓没抓完无关。
        # （孤岛页那类靠「没看到」下结论的规则才需要完整性门槛）
        for title, urls in ctx.title_index.items():
            if len(urls) < 2:
                continue
            yield self._site_issue(
                ctx,
                {
                    "title": title,
                    "url_count": len(urls),
                    "duplicate_ratio": round(len(urls) / max(len(ctx.all_pages), 1), 3),
                    "sample_urls": urls[:10],
                },
            )


@reg.register
class MetaDescriptionMissing(Rule):
    code = "meta.missing"
    severity = Severity.HIGH
    title = "页面缺少 meta description"
    description = "description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。"
    fix_hint = "补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。"
    fix_example = '<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code == 200 and not page.meta_description:
            yield self._issue(page, {"meta_description_found": False})


@reg.register
class MetaDescriptionDuplicate(Rule):
    code = "meta.duplicate"
    severity = Severity.MEDIUM
    scope = Scope.SITE
    title = "多个页面 meta description 相同"
    description = "相同的 description 让这些页面在搜索结果里长得一样，用户没有理由点开第二个。"
    fix_hint = "每页 description 描述该页面独有的内容与卖点。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        for desc, urls in ctx.meta_index.items():
            if len(urls) < 2:
                continue
            yield self._site_issue(
                ctx,
                {
                    "meta_description": desc[:200],
                    "url_count": len(urls),
                    "sample_urls": urls[:10],
                },
            )


@reg.register
class H1Missing(Rule):
    code = "h1.missing"
    severity = Severity.HIGH
    title = "页面没有 H1 标题"
    description = "H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。"
    fix_hint = "加一个 H1 写清页面主标题，位置放在正文开头。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ⚠️ 与 title.missing 同源：静态 HTML 里没看到 h1，不等于渲染后没有。
        # 实测 www.agoda.com：737KB 页面 h1_count=0，同时
        # likely_js_rendered=True——它是个内容饱满的电商首页，只是正文在
        # 客户端跑完之后才有。在这种页面上报 HIGH「页面没有 H1」是纯噪音。
        #
        # ⚠️ 但**不要**因此放松对普通页面的判据。实测 arxiv.org 与
        # bellroy.com 首页确实一个 <h1> 都没有（直接 grep 原始 HTML：
        # `<h1` 命中 0 次，arxiv 有 9 个 <h2>；两者 likely_js_rendered 均为
        # False，是服务端渲染的静态页面）。那两条是**真问题、如实属实**，
        # 本条规则保持原样照报——不是提取层漏采，是页面真的没有 h1。
        if page.likely_js_rendered:
            return
        if page.status_code == 200 and not page.h1:
            yield self._issue(page, {"h1_count": 0})


@reg.register
class H1Multiple(Rule):
    code = "h1.multiple"
    severity = Severity.INFO
    title = "模板重复渲染了多个内容完全相同的 H1"
    description = (
        "多个 H1 本身不是问题：HTML5 明确允许，Google 也公开表示不影响索引或排名，"
        "站名 H1 + 文章标题 H1 是很常见且合理的设计。\n"
        "⚠️ 所以这条只报一种情况：**多个 H1 的内容完全一样**。"
        "那通常是模板被重复渲染，属于真 bug；如果只是内容不同，保持现状即可，不要为了消掉这条去改版面。"
    )
    fix_hint = (
        "保留最具体的一个 H1，其余内容完全相同的降为 H2 或改为普通文本。"
        "如果多个 H1 内容本就不同（站名 + 文章标题），无需处理。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if len(page.h1) <= 1:
            return
        normalized = {h.strip().lower() for h in page.h1 if h.strip()}
        # ★ 只有「内容完全相同」才算问题。这是本站实测数据倒逼的：
        #   23 站回归里 h1.multiple 报 14 条，0 条属实、10 条是噪音，
        #   全部是「站名 H1 + 文章标题 H1」这种合理设计。
        #   旧版无论是否重复都报一条 INFO，而它自己的描述却写着
        #   「不要为了消掉这条去改版面」——规则自相矛盾，用户只能二选一：
        #   听规则的改版面，或者无视报告。这正是噪音的代价。
        #   上一版已降级为 INFO，但误报回归证明降级不够：噪音仍占全部发现项的
        #   可观比例。现在只在真重复时触发。
        if len(normalized) >= len(page.h1):
            return
        yield self._issue(
            page,
            {
                "h1_count": len(page.h1),
                "h1_list": page.h1[:5],
                "duplicated": True,
                "verdict": "review_worthwhile",
                "verdict_explain": "存在内容完全相同的 H1，多半是模板重复渲染",
            },
        )


@reg.register
class CanonicalMissing(Rule):
    code = "canonical.missing"
    severity = Severity.MEDIUM
    title = "页面缺少 canonical 标签"
    description = "URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。"
    fix_hint = '在 <head> 里加 <link rel="canonical" href="本页的规范地址">。'
    fix_example = '<link rel="canonical" href="https://example.com/product/123">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 首页通常不需要 canonical，跳过以减少噪音
        if page.url.rstrip("/") in (f"https://{ctx.domain}", f"http://{ctx.domain}"):
            return
        if page.status_code == 200 and not page.canonical:
            yield self._issue(page, {"canonical_found": False})


# ── canonical 常见等价写法 ──────────────────────────────────────
#
# 真实样本里 canonical.conflict 的 21 条，除 1 条外全都是「同一篇内容的
# 正规变体写法」，不是权重转移：canonical 剥掉了跟踪参数、加了 /index、
# 指了 /home、去掉了语言前缀、或指向同名 PDF。
#
# 这些**不该按 MEDIUM「canonical 指向其他页面」报**——那句话会让用户去改
# 本来正确的写法。按同文件里 case_only_difference 的既有惯例处理：
# 降 INFO + 在 evidence 里说清是哪一种变体，而不是静默丢弃。

# 结尾可省略的「首页别名」。真实样本：cs.cmu.edu/→/index、
# cs.umd.edu/→/home、who.int/europe/home→/europe。
_TRAILING_ALIASES = frozenset({
    "index", "index.html", "index.htm",
    "home", "home.html", "home.htm",
    "default", "default.html", "default.htm",
})

_BENIGN_VARIANT_REASONS = {
    "query_dropped": "canonical 去掉了当前页带的查询参数（跟踪/会话参数），路径本身是同一页",
    "index_or_home_alias": "canonical 用 /index、/home、/default 指向同一页（站点自己的索引别名）",
    "pdf_variant": "canonical 指向同一篇文章的 PDF 版本",
    "lang_prefix": "canonical 去掉了语言前缀（如 /de/cloud/x → /cloud/x），指向同一份内容",
}

# 这两类**彻底闭嘴**，连 INFO 都不报。
#
# 我第一版把它们降成 INFO，结果是：真误报 8→1 确实修好了，但严格准确率
# 从 6% 掉到 0% —— 因为「判对但不值得报」在我的核对器里同样算噪音、
# 同样扣分。降级只是给误报换了个标签，没有消除它。
#
# 判据不是「这个数字好不好看」，而是「用户看到这条会做什么」：
#   - query_dropped：剥掉 utm 参数是全行业标准做法，告知用户零价值。
#   - index_or_home_alias：站点用 /index 指首页是它自己的索引别名，
#     不是问题。cs.cmu.edu 首页这么写用了二十年。
# 两类的共同点：**报告它们等于让用户去改本来正确的东西**，而这正是
# 我今晚修 h1.multiple、noindex、canonical 大小写时一直在治的病。
#
# 另两类刻意留在 INFO，因为闭嘴会造成**漏报**（比误报更坏）：
#   - lang_prefix：/de/ 页 canonical 指向非本地化版本，德语用户搜不到
#     德语页，有真实排名后果。
#   - pdf_variant：指向同名 PDF 是刻意的选择，值得知道。
_SILENT_VARIANTS = frozenset({"query_dropped", "index_or_home_alias"})


def _split_url(url: str) -> tuple[str, str]:
    """拆成 (host 去 www., path)，不碰 query——query 差异由调用方单独判。"""
    p = urlsplit(url)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return host, path


def _strip_trailing_alias(path: str) -> str:
    """去掉结尾的 /index、/home、/default 这类别名段。

    按**整段**匹配而不是后缀匹配：否则 /myindex 会被当成 /my + index
    而错误折叠，那会把真正不同的两页当成同一页。
    """
    segs = [s for s in path.split("/") if s]
    if segs and segs[-1].lower() in _TRAILING_ALIASES:
        segs = segs[:-1]
    return "/" + "/".join(segs) if segs else "/"


def _strip_lang_prefix(path: str) -> str:
    """去掉开头一段语言标签（de、zh-CN、en_US…）。

    只在还剩至少两段时才剥：否则 /de 会被剥成 /，任何两字母目录都会塌掉。
    """
    segs = [s for s in path.split("/") if s]
    if len(segs) >= 2 and re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2,4})?", segs[0], re.I):
        return "/" + "/".join(segs[1:])
    return path


def _benign_canonical_variant(current: str, canonical: str) -> str | None:
    """canonical 是否只是当前页的「正规变体写法」。

    返回 _BENIGN_VARIANT_REASONS 的 key；不是这类变体则返回 None，
    交回规则按真冲突处理。
    """
    hc, pc = _split_url(current)
    hk, pk = _split_url(canonical)
    if hc != hk:
        return None  # 跨域 canonical：那是另一回事，不能在这里放行

    a, b = _strip_trailing_alias(pc), _strip_trailing_alias(pk)
    if a == b:
        # 去别名后一致，但原文不同 → 是别名写法；原文就一致 → 只差 query
        return "index_or_home_alias" if pc != pk else "query_dropped"

    # PDF 变体：nature.com/articles/X → /articles/X.pdf
    if b.lower().endswith(".pdf") and b[:-4] == a:
        return "pdf_variant"

    # 语言前缀：naaptol.com/ro/print.html → /print
    def bare(p: str) -> str:
        return p[:-5] if p.lower().endswith(".html") else p

    if _strip_lang_prefix(bare(a)) == bare(b) or _strip_lang_prefix(bare(b)) == bare(a):
        return "lang_prefix"
    return None


@reg.register
class CanonicalConflict(Rule):
    code = "canonical.conflict"
    severity = Severity.MEDIUM
    title = "canonical 指向了其他页面（需确认是否有意为之）"
    description = (
        "canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。"
        "这可能是有意为之（内容已合并、历史版本别名、分页主页面），"
        "也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，"
        "请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。"
    )
    fix_hint = "逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.canonical or page.status_code != 200:
            return
        current = page.final_url or page.url
        # 比较时忽略协议、www、末尾斜杠与 index.html 等价形式
        if normalize_url(page.canonical) == normalize_url(current):
            return

        # 回访 canonical 目标，用结果区分「真 bug」与「有意合并」
        target_status = (ctx.site_facts or {}).get("canonical_target_status", {}).get(
            normalize_url(page.canonical)
        )

        evidence: dict[str, object] = {
            "canonical": page.canonical,
            "page_url": current,
            "canonical_target_status": target_status,
        }

        # 仅 path 大小写不同：指向的还是自己（path 按 URL 规范区分大小写，
        # 但站点往往两种都服务）。这是模板大小写不一致，不是权重转移，
        # 按 MEDIUM 报会让人去改本来正确的东西——降到 INFO 并说清是什么。
        if same_url_ignoring_path_case(page.canonical, current):
            evidence["verdict"] = "case_only_difference"
            evidence["verdict_explain"] = (
                "canonical 与当前页仅路径大小写不同，指向的仍是本页；"
                "若站点两种形式都返回 200，保持现状即可"
            )
            yield self._issue(page, evidence, severity=Severity.INFO)
            return

        # 常见等价写法（/index、/home、语言前缀、同名 PDF、参数剥离）
        # 是同一页的不同写法，不是权重转移。按 case_only_difference 的
        # 既有惯例降 INFO 并说明是哪一种，而不是报成冲突让用户去改。
        benign = _benign_canonical_variant(current, page.canonical)
        if benign:
            if benign in _SILENT_VARIANTS:
                # 不是问题，保持沉默。见 _SILENT_VARIANTS 注释。
                return
            evidence["verdict"] = f"benign_variant:{benign}"
            evidence["verdict_explain"] = _BENIGN_VARIANT_REASONS[benign]
            yield self._issue(page, evidence, severity=Severity.INFO)
            return

        if target_status in (404, 410, None) and target_status is not None:
            # 目标页不存在 → 确定是 bug
            evidence["verdict"] = "likely_bug"
            yield self._issue(page, evidence, severity=Severity.CRITICAL)
        elif target_status and target_status >= 400:
            evidence["verdict"] = "likely_bug"
            yield self._issue(page, evidence, severity=Severity.HIGH)
        else:
            # 目标页正常存在 → 多半是有意为之，只作提醒
            evidence["verdict"] = "possibly_intentional"
            yield self._issue(page, evidence)


@reg.register
class NoindexPresent(Rule):
    code = "noindex.present"
    severity = Severity.CRITICAL
    title = "页面被 noindex 屏蔽收录"
    description = "noindex 会让页面完全不出现在搜索结果里。这通常是开发环境忘记删，或者模板改版时误加。"
    fix_hint = "如果页面应该被收录，删掉 noindex；如果是故意屏蔽（如分页页），请在 sitemap 中也排除它。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ⚠️ 错误页面的 noindex 是**正确做法**，不是 bug。
        # 真实样本：developer.mozilla.org/en-US/404 返回 404 且带
        # noindex, nofollow——这是标准配置。旧版不看状态码，把它判成
        # CRITICAL「页面被屏蔽收录」，等于让用户把 404 页从屏蔽名单里
        # 摘出来，好让搜索引擎收录一个 404。这是典型的「规则对了、
        # 用户照做反而更糟」。
        if page.status_code >= 400:
            return
        robots = (page.robots_meta or "").lower()
        tokens = set(robots.replace(",", " ").split())
        if tokens & {"noindex", "none"}:
            yield self._issue(page, {"robots_meta": page.robots_meta})


@reg.register
class ImageAltMissing(Rule):
    code = "img.alt.missing"
    severity = Severity.MEDIUM
    title = "图片缺少 alt 文本"
    description = "alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。"
    fix_hint = '补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。'
    fix_example = '<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        missing = [img.src for img in page.images if img.alt is None]
        if missing:
            yield self._issue(
                page,
                {
                    "missing_count": len(missing),
                    "total_images": len(page.images),
                    "sample_srcs": missing[:5],
                },
            )


@reg.register
class ImageAltGeneric(Rule):
    code = "img.alt.generic"
    severity = Severity.LOW
    title = "图片 alt 是无意义占位文本"
    description = 'alt 写成 "image"、"图片"、"1.jpg" 这类等于没写，图片搜索拿不到任何语义信息。'
    fix_hint = "改成描述图片实际内容的文字。"

    _GENERIC = {
        "image", "img", "picture", "photo", "图片", "图像", "照片",
        "1", "2", "3", "图片1", "图片2", "untitled", "placeholder", "icon",
    }

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        generic = [
            img.src
            for img in page.images
            if img.alt and img.alt.strip().lower() in self._GENERIC
        ]
        if generic:
            yield self._issue(page, {"generic_count": len(generic), "sample_srcs": generic[:5]})


@reg.register
class LinkNoAnchor(Rule):
    code = "link.noanchor"
    severity = Severity.MEDIUM
    title = "内部链接锚文本为空"
    description = "空锚文本（如 `<a href=\"/x\"></a>`）对用户和搜索引擎都没有传递任何信息，也会带来可访问性问题。"
    fix_hint = "给链接加上描述性锚文本。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 排除装饰性链接（<a aria-hidden="true"><img alt=""></a>）：它们对可见
        # 用户、读屏软件和爬虫都不构成锚文本，让用户去改等于让人改本来正确
        # 的东西。ocw.mit.edu 首页 114 个「空锚」里 96 个是这种（实测）。
        empties = [
            l.href
            for l in page.links
            if l.kind.value == "internal" and not l.anchor and not l.decorative
        ]
        # 只报「本页有多个空锚」的情况：单个往往是无害的 UI 元素
        if len(empties) >= 2:
            yield self._issue(
                page,
                {
                    "empty_anchor_count": len(empties),
                    "sample_hrefs": empties[:5],
                    "excluded_decorative": sum(
                        1
                        for l in page.links
                        if l.kind.value == "internal" and not l.anchor and l.decorative
                    ),
                },
            )


@reg.register
class DepthExcessive(Rule):
    code = "depth.excessive"
    severity = Severity.MEDIUM
    title = "页面点击层级过深"
    description = "超过 4 层的页面很难被抓取和被用户点到，权重传递也会被削弱。"
    fix_hint = "在导航或页脚增加直达链接，把重要页面压到 3 层以内。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.depth > 4:
            yield self._issue(
                page, {"depth": page.depth, "url": page.url}, title=self.title
            )


@reg.register
class OrphanPage(Rule):
    code = "orphan.page"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "孤岛页面：没有任何内链指向"
    description = "既不在导航里、也没有其他页面链向它，只能靠 sitemap 被发现。这类页面很难获得权重，也几乎不可能有流量。"
    fix_hint = "在相关内容的文章或列表页中加入指向它的内链。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ★ 数据充分性门槛：只抓到一小部分页面时，“没有入链”可能只是没被抓到。
        # 覆盖率不够时保持沉默——大面积误报会直接毁掉工具的可信度。
        if not ctx.has_enough_data():
            return
        # 只看可索引的 HTML 页面，PDF/图片等不参与孤岛判断
        candidates = [
            p for p in ctx.all_pages if p.status_code == 200 and p.is_html and not p.error
        ]
        orphans = []
        for p in candidates:
            inbound = ctx.inbound_links.get(p.url, 0) + ctx.inbound_links.get(
                p.final_url or p.url, 0
            )
            if inbound == 0:
                orphans.append(p.url)
        if orphans:
            yield self._site_issue(
                ctx,
                {
                    "orphan_count": len(orphans),
                    "scanned_pages": len(candidates),
                    "total_discovered": ctx.discovered,
                    "coverage": round(ctx.coverage, 3),
                    "sample_urls": orphans[:20],
                },
            )


@reg.register
class MixedContent(Rule):
    code = "http.mixed_content"
    severity = Severity.HIGH
    title = "HTTPS 页面存在混合内容"
    description = "HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。"
    fix_hint = "把所有 http:// 资源改成 https://，或用协议相对路径。"
    fix_example = '把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.has_mixed_content:
            yield self._issue(
                page,
                {
                    "page_url": page.final_url or page.url,
                    "offending_resources": page.mixed_content_samples,
                    "note": "只统计 img/script/link/iframe 等子资源，不含 <a href> 超链接",
                },
            )


@reg.register
class SchemaMissing(Rule):
    code = "schema.missing"
    severity = Severity.INFO
    scope = Scope.SITE
    title = "本站未使用结构化数据（可选增强）"
    description = (
        "结构化数据（JSON-LD）能让搜索引擎理解页面实体，是拿到富媒体搜索结果"
        "（商品星级、FAQ 折叠、文章日期等）的前提。\n"
        "⚠️ 但这是**可选增强，不是缺陷**：12 站实测里，它贡献了全部发现项的 38%，"
        "而其中没有一条是用户「必须修」的问题。写与不写都不影响排名。\n"
        "所以这里只做站点级一次性提示：加了是加分项，不加也完全正常。"
    )
    fix_hint = (
        "仅在你想拿富媒体搜索结果时才需要。商品页用 Product、问答页用 FAQ、"
        "文章页用 Article。多数内容站可以完全不做。"
    )
    fix_example = (
        '<script type="application/ld+json">\n'
        '{"@context":"https://schema.org","@type":"Product",'
        '"name":"防水登山鞋","offers":{"@type":"Offer","price":"299"}}\n'
        "</script>"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 为什么改成 SITE 级：12 站实测里这条贡献了 38% 的发现项，
        # 而没有一条是用户「必须修」的问题。「本站没写 JSON-LD」是一条建议，
        # 按页报成 N 遍就是噪音。
        #
        # ⚠️ SITE 级规则的 page 参数是哨兵对象（_EMPTY_PAGE, status_code=0），
        # **绝不能读 page 的字段**——读到的永远是空值，规则会静默失效。
        # 必须走 ctx.all_pages。这个坑真的踩过：改完规则不报错，就是不触发。
        if not ctx.has_enough_data():
            return

        observed = [
            p for p in ctx.all_pages if p.status_code == 200 and p.is_html
        ]
        if not observed:
            return
        with_jsonld = [p for p in observed if p.jsonld or p.microdata_types]
        if with_jsonld:
            return  # 有的页面写了就不报

        yield self._site_issue(
            ctx,
            {
                "jsonld_count": 0,
                "microdata_count": 0,
                "pages_observed": len(observed),
                "verdict": "optional_enhancement",
                "verdict_explain": "可选增强：写与不写都不影响排名，仅影响是否能拿富媒体结果",
            },
        )


@reg.register
class Soft404(Rule):
    code = "soft404"
    severity = Severity.MEDIUM
    title = "疑似软 404（需确认）"
    description = (
        "页面返回 200 但正文极少，搜索引擎会识别为软 404 并停止索引。"
        "⚠️ 但索引页、目录页、标签页天生内容少，不一定是问题——"
        "工具会提供判定信号，请确认：这个页面是“该有内容却没有”，还是“本身就是列表页”。"
    )
    fix_hint = "如果确实是空页面：返回真正的 404 状态码，或补上内容。如果是索引/列表页：忽略本条即可。"

    # 这些 URL 形态本身就代表目录/索引页
    _INDEX_HINTS = (
        "index", "genindex", "py-modindex", "category", "/tag/", "/list",
        "archives", "sitemap", "?page=", "/page/",
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.content_is_thin:
            return

        # ── 尺子校准：先排掉「量错了」，再看是不是真软 404 ──
        #
        # ⚠️ 这里的 content_is_thin 来自 trafilatura 抽的 page.text，而
        # trafilatura **会主动剥掉 nav/footer/header**。导航重的页面 word_count
        # 必然被压到 300 词以下，于是规则对着一个内容充足的页面报「疑似软 404」。
        # 实测第三批 72 条 soft404 里有 55 条是这么来的：japanpost.jp 首页
        # 剥后 74 字符、含导航 1433 字符、223 条站内出链，那不是空页面。
        #
        # 所以先用第二个尺子 full_text_length（含导航页脚）复核。只有连它也
        # 说这页没东西，才算「可能是空页面」。这样用户才不会被引导去改
        # 一个根本没坏的家页。
        if page.full_text_length >= 800:
            return

        # ── 「没渲染出来」不等于「页面是空的」 ──
        #
        # ⚠️ 这条不排，后面会报出 **HIGH** 级「高危：你这页是空页面」。
        # 实测 www.agoda.com 一个 733KB 的页面，全量可见文本 **0 字**，
        # content_is_thin=True，内链 3 条——上面那道 full_text_length
        # 也拦不住它（0 < 800）。可它不是空页面，它是个 JS 渲染的电商站，
        # 内容全在客户端跑完之后才有。用户在报告里看到这条会去改一个
        # 内容饱满的首页。
        #
        # 规则层光看 word_count / full_text_length 分不出两件事：
        #   这页没内容      vs      这页内容我看不见
        # 必须由提取层把 likely_js_rendered 递过来——它是在
        # extract._looks_js_rendered_shell 里实测 HTML 体积、挂载点、
        # 出链数得出的，不是猜的。
        if page.likely_js_rendered:
            return

        path = (page.url or "").lower()
        # 入链数在 ctx 上（build_context 算的），不是 site_facts
        inbound = ctx.inbound_links.get(page.url, 0) + ctx.inbound_links.get(
            page.final_url or page.url, 0
        )

        # ── 区分「真软 404」与「正常的短索引页」 ──
        # 判据：目录/索引页会挂大量出链（供用户跳转），且往往被很多页面链接；
        #       而真正的空页面既无出链也几乎无入链。
        outbound = page.internal_link_count
        looks_like_index = any(h in path for h in self._INDEX_HINTS)

        if looks_like_index or outbound >= 10:
            verdict = "likely_index_or_hub"
            severity = Severity.INFO
        elif inbound == 0 and outbound <= 3:
            verdict = "likely_true_soft404"
            severity = Severity.HIGH
        else:
            verdict = "uncertain"
            severity = Severity.MEDIUM

        yield self._issue(
            page,
            {
                "word_count": page.word_count,
                "text_preview": page.text[:120],
                "status_code": page.status_code,
                "internal_outbound_links": outbound,
                "inbound_links": inbound,
                "url_looks_like_index": looks_like_index,
                "verdict": verdict,
                "verdict_explain": {
                    "likely_index_or_hub": "出链多、URL 形似索引页，大概率是正常的目录/列表页",
                    "likely_true_soft404": "既无出链也几乎无入链且内容极少，大概率是空页面",
                    "uncertain": "信号不明确，请人工看一眼",
                }[verdict],
            },
            severity=severity,
        )


@reg.register
class SitemapMissing(Rule):
    code = "sitemap.missing"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "站点没有可用的 sitemap"
    description = "没有 sitemap 时，搜索引擎只能靠内链发现页面，新页面和深埋页面的收录速度会明显变慢，抓取预算也用得更浪费。"
    fix_hint = "生成 XML sitemap，在 robots.txt 里声明它，并提交到 Google Search Console 和百度搜索资源平台。"
    fix_example = (
        "User-agent: *\n"
        "Allow: /\n"
        "Sitemap: https://example.com/sitemap.xml"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        if "sitemap_found" not in facts:
            return  # 爬虫没探测 sitemap（如手工喂的页面），不误报
        if not facts["sitemap_found"]:
            yield self._site_issue(
                ctx,
                {
                    "tried_paths": facts.get("sitemap_tried", []),
                    "error": facts.get("sitemap_error"),
                },
            )


@reg.register
class RobotsMissing(Rule):
    code = "robots.missing"
    severity = Severity.MEDIUM
    scope = Scope.SITE
    title = "缺少 robots.txt"
    description = "robots.txt 不是必需的，但它的存在能控制抓取范围、声明 sitemap，并避免爬虫浪费预算在后台等无价值路径上。"
    fix_hint = "放一个 robots.txt 到根目录，并声明 sitemap 地址。"
    fix_example = "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        status = facts.get("robots_status")
        if status is None:
            return
        if status == 404:
            yield self._site_issue(ctx, {"robots_url": facts.get("robots_url"), "status": 404})


@reg.register
class RobotsBlocksBots(Rule):
    code = "robots.blocks_own_site"
    severity = Severity.CRITICAL
    scope = Scope.SITE
    title = "robots.txt 屏蔽了搜索引擎收录全站"
    description = "这是最严重也最容易犯的错：Disallow: / 会让整站从搜索结果中消失。如果本意是不让某个目录被索引，应该只屏蔽那个目录，而不是全站。"
    fix_hint = "改成 Allow: / 并针对特定目录 Disallow，确认规则上线前先在 Google Search Console 的 robots 测试工具里验证。"
    fix_example = "User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /search?"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        directives = facts.get("robots_directives") or []
        for ua, rules in directives:
            if ua not in ("*", "googlebot", "baiduspider", "bingbot"):
                continue
            for raw in rules:
                rule = raw.split("#")[0].strip()
                if not rule:
                    continue
                parts = rule.split(":", 1)
                if len(parts) != 2:
                    continue
                directive, value = parts[0].strip().lower(), parts[1].strip()
                if directive == "disallow" and value == "/":
                    yield self._site_issue(
                        ctx,
                        {"user_agent": ua, "directive": f"Disallow: {value}",
                         "robots_url": facts.get("robots_url")},
                    )


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------


def _is_cjk(text: str) -> bool:
    """判断是否包含中日韩字符——用于切换中英文长度阈值。"""
    return any("一" <= ch <= "鿿" for ch in text)
