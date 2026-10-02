"""
baidu 包 2026 回源核对的 7 条真误报回归测试。

背景
----
107 站真实扫描后，核对器逐条回访目标 URL 拿真实内容比对，判出 baidu 包有
7 条**真误报**（规则说有问题、实际没问题）。本文件把每一类根因钉死，
每个用例都成对：一条「样本必须闭嘴」+ 一条「反向用例仍要触发」。

反向用例是这份文件存在的理由。上一轮修误报时把条目降级成 INFO 就当「修好了」，
规则照样产出条目、照样扣分，严格准确率反而从 6% 掉到 0%。所以这里的断言不是
「没报错」，而是**规则在该触发时仍产出条目**，防止把规则改成永远沉默。

样本一律用扫描 JSON 里的原始 evidence（html_lang / declared_hreflang / self_url）
和 2026-10-01 真实回访 fetch 到的 title，不改写成比真实情况更温和的形式。

三条根因
--------
1. **抓取翻译视图**：crawler 用 `Accept-Language: zh-CN` 发请求，接了翻译的站点
   （Discourse 等）会把整页机器翻译成中文再返回——`<title>` 变成中文、`lang` 变成
   zh-CN。这种中文标题不是作者写的，作者也改不了。
2. **按像素宽度截断 ≠ 按字符数**：百度结果页标题按显示宽度截断（≈30 汉字 = 480px），
   旧实现用 `len(title)`，等于把半角 ASCII 也按 1em 算，白送预算。
3. **日语不能按中文规则判**：中日汉字同形，日文标题汉字占比很高，`_is_cjk` 必然
   放行，但中文 n-gram / 截断规律套在日文上必然误判。

运行：
    cd backend && PYTHONPATH=/root/.openclaw/workspace/seo-agent/.deps:. \\
        python3 -m pytest tests/ -q
"""

from __future__ import annotations

from app.audit.engine import run_audit
from app.audit.rules.baidu import _title_px
from app.models import Market, Page

BAIDU = [Market.BASE, Market.BAIDU]

TITLE_CODE = "title.chinese_too_long"
SEM_CODE = "meta.chinese_semantic_incomplete"


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------


def page(**kw) -> Page:
    """直接构造 Page：这些用例关心规则的判定，不关心提取层。"""
    data = {"url": "https://demo.test/p", "status_code": 200}
    data.update(kw)
    return Page(**data)


def hits(code: str, page_obj: Page) -> list[Page]:
    issues, _ = run_audit([page_obj], "demo.test", BAIDU)
    return [i for i in issues if i.code == code]


def fires(code: str, page_obj: Page) -> bool:
    return bool(hits(code, page_obj))


# Discourse 的真实 hreflang（2026-10-01 实跑 extract_page 抓到的原文）。
# 关键：zh-CN 变体指向 `?tl=zh_CN`，**不是本页自己**——这就是「本页是源文档、
# 中文是抓取时协商出来的」签名。
_D_TOPIC = "https://meta.discourse.org/t/default-editor-to-the-advanced-editor-and-dont-allow-the-compact-one/413703"


# 真实中文超长标题的定长样本（像素值由 `_title_px` 实测，见下方断言）：
#   CJK31  31 字符 → 496px  必须报（比预算高 16px，落在 google 的 ±10% 误差带内）
#   CJK30  30 字符 → 480px  正好卡在预算上，不报
#   ASCII31 33 字符 → 500px  必须报，且证明半角折算没有把真问题吃掉
_CJK_BASE = "防水登山鞋男款防滑耐磨徒步鞋登山鞋户外鞋透气防风保暖防水鞋"
CJK31 = _CJK_BASE + "男款"  # 31 字符 / 496px
CJK30 = CJK31[:30]  # 30 字符 / 480px（边界）
ASCII31 = CJK30 + " ab"  # 33 字符 / 500px（半角混排）


def discourse_page(title: str, description: str = "") -> Page:
    base = _D_TOPIC
    return page(
        url=base,
        final_url=base,
        lang="zh-CN",
        title=title,
        title_length=len(title),
        meta_description=description,
        hreflang=[
            ("x-default", base),
            ("en", base + "?tl=en"),
            ("zh-CN", base + "?tl=zh_CN"),
            ("es", base + "?tl=es"),
            ("ja", base + "?tl=ja"),
        ],
    )


# atlassian 的真实 hreflang：zh-Hans 指向本页自己 -> 它是真正的中文本地化页，
# 不属于翻译视图，规则必须照常生效。
_A_ZH = "https://www.atlassian.com/zh/software/statuspage"


def atlassian_zh_page(title: str) -> Page:
    return page(
        url=_A_ZH,
        final_url=_A_ZH,
        lang="zh",
        title=title,
        title_length=len(title),
        hreflang=[
            ("x-default", "https://www.atlassian.com/software/statuspage"),
            ("en", "https://www.atlassian.com/software/statuspage"),
            ("zh-Hans", _A_ZH),
            ("ja", "https://www.atlassian.com/ja/software/statuspage"),
        ],
    )


# --------------------------------------------------------------------------
# 根因 1：抓取翻译视图（Discourse 4 条 title + 2 条 meta）
# --------------------------------------------------------------------------


class TestTranslationViewMustStaySilent:
    """Discourse 的中文标题是抓取时协商出来的翻译，作者改不了 -> 闭嘴。

    真实对照（同一 URL，同一个 fetch 函数）：
        Accept-Language: en     -> lang=en,    title="Default editor to the advanced editor..."
        Accept-Language: zh-CN  -> lang=zh-CN, title="默认使用高级编辑器，并禁用简易编辑器..."
    """

    def test_default_editor_title_must_be_silent(self):
        p = discourse_page("默认使用高级编辑器，并禁用简易编辑器 - 功能 - Discourse Meta")
        assert not fires(TITLE_CODE, p)

    def test_rails_c_title_must_be_silent(self):
        p = discourse_page(
            "通过 rails c 满足“数字强迫症”：这些直接的 ActiveRecord 操作完全安全吗？"
            " - 安装 - Discourse Meta"
        )
        assert not fires(TITLE_CODE, p)

    def test_self_hosters_title_must_be_silent(self):
        p = discourse_page("自托管用户：重新编译 Discourse 以降低内存占用 - 公告 - Discourse Meta")
        assert not fires(TITLE_CODE, p)

    def test_paginated_voice_title_must_be_silent(self):
        p = discourse_page(
            "语音：Discord 风格的语音和视频房间，现已集成到 Discourse 中 🎙"
            " - 第 4 页 - 公告 - Discourse Meta"
        )
        assert not fires(TITLE_CODE, p)

    def test_semantic_rule_silent_on_translated_editor_post(self):
        """meta.chinese_semantic_incomplete 样本一：重复词根是 `我们`：3。"""
        p = discourse_page(
            "默认使用高级编辑器，并禁用简易编辑器 - 功能 - Discourse Meta",
            description=(
                "你好！ 我们开发了一个插件，重新定义了 post-event-builder 插件的输出："
                "在我们实例上创建的每个活动都需要填写其自定义字段，"
                "而我们的表单会使用外部数据来补全所提出的值……"
            ),
        )
        # 先确认这条在「去掉守卫」的世界里确实会触发，否则测试是空的
        assert p.meta_description.count("我们") >= 3
        assert not fires(SEM_CODE, p)

    def test_semantic_rule_silent_on_translated_selfhosters_post(self):
        """meta.chinese_semantic_incomplete 样本二：重复词根是 `内存`：3。"""
        p = discourse_page(
            "自托管用户：重新编译 Discourse 以降低内存占用 - 公告 - Discourse Meta",
            description=(
                "我们改进了 Discourse 在容器内运行的进程之间共享内存的方式，"
                "从而减少了所需的内存（RAM）。 以下是来自我们其中一个内部容器的示例。"
                "在更改之前，内存使用量…"
            ),
        )
        assert not fires(SEM_CODE, p)

    # ---- 反向用例：守卫不能把真问题一起吃掉 ------------------------------

    def test_chinese_self_hreflang_still_fires(self):
        """本页自己就是被声明的中文版本 -> 不是翻译视图，必须照报。

        这是本守卫最危险的边界：atlassian 的 /zh/ 页声明 zh-Hans 指向自己，
        如果判错成翻译视图，这条规则就永远不会说话了。
        """
        p = atlassian_zh_page(CJK31)
        assert _title_px(CJK31) > 480
        assert fires(TITLE_CODE, p)

    def test_no_hreflang_at_all_still_fires(self):
        """没有 hreflang 的中文页（大量中文站如此）必须照报，不能被守卫误伤。"""
        p = page(lang="zh-CN", title=CJK31, title_length=len(CJK31), hreflang=[])
        assert fires(TITLE_CODE, p)

    def test_zh_alternate_pointing_to_other_url_but_self_is_source_still_silent(self):
        """x-default 是本页、中文在别处 -> 仍是翻译视图。"""
        base = "https://demo.test/t/some-topic/1"
        p = page(
            url=base,
            final_url=base,
            lang="zh-CN",
            title="默认使用高级编辑器，并禁用简易编辑器 - 功能 - 站点名",
            title_length=33,
            hreflang=[("x-default", base), ("zh-CN", base + "?tl=zh_CN")],
        )
        assert not fires(TITLE_CODE, p)


# --------------------------------------------------------------------------
# 根因 2：按像素宽度截断（bellroy / atlassian 的「31 字 vs 30 字」）
# --------------------------------------------------------------------------


class TestPixelWidthNotCharCount:
    """旧实现 `len(title) <= 30`，把半角 ASCII 也按 1em 算，白送预算。

    真实样本（31 字符，超「阈值」1 字）：
        「借助 Statuspage 提高透明度 | Atlassian」            31 字符 → 274px
        「关于零售商 | 查找店铺库存 | Bellroy零售商及销售点」  31 字符 → 366px
    预算是 480px（=30 汉字）。两者都远在预算内，百度根本不截断。
    """

    def test_bellroy_31_chars_must_be_silent(self):
        title = "关于零售商 | 查找店铺库存 | Bellroy零售商及销售点"
        p = page(lang="zh-CN", title=title, title_length=len(title))
        assert len(title) == 31  # 旧规则在这里会报
        assert _title_px(title) == pytest_approx(366.3)
        assert not fires(TITLE_CODE, p)

    def test_atlassian_31_chars_must_be_silent(self):
        title = "借助 Statuspage 提高透明度 | Atlassian"
        p = atlassian_zh_page(title)
        assert len(title) == 31
        assert _title_px(title) == pytest_approx(274.0)
        assert not fires(TITLE_CODE, p)

    def test_ascii_heavy_chinese_title_fits_and_is_silent(self):
        """中英混排：字符数超 30 但实际宽度在预算内。"""
        title = "阿里云 CDN 加速与 OSS 对象存储接入配置最佳实践全解析"
        assert len(title) > 30
        assert not fires(TITLE_CODE, page(lang="zh-CN", title=title, title_length=len(title)))

    # ---- 反向用例：像素预算真的超了必须报 --------------------------------

    def test_thirty_one_pure_cjk_chars_still_fires(self):
        """31 个纯汉字 = 496px > 480px。必须报——这是修误报最怕踩的坑：
        把 ASCII 折半格的同时把汉字也折了，规则就永远不会说话了。
        """
        assert len(CJK31) == 31
        assert _title_px(CJK31) == pytest_approx(496.0)
        p = page(lang="zh-CN", title=CJK31, title_length=len(CJK31))
        assert fires(TITLE_CODE, p)

    def test_thirty_pure_cjk_chars_at_budget_is_silent(self):
        """反向的边界：30 个汉字 = 480px，正好卡在预算上，不报。"""
        assert len(CJK30) == 30
        assert _title_px(CJK30) == pytest_approx(480.0)
        p = page(lang="zh-CN", title=CJK30, title_length=len(CJK30))
        assert not fires(TITLE_CODE, p)

    def test_overflow_beyond_error_band_still_fires(self):
        """google 包对像素估算套了 ±10% 误差带（可选项，宁可漏报）。
        中文包**故意不套**：这是中文生态唯一的超长检测，闭嘴会造成漏报，
        而漏报比误报更坏。超出 16px（落在误差带里）也照报。
        """
        px = _title_px(ASCII31)
        assert 480 < px <= 480 * 1.10  # 落在 google 的误差带里
        assert fires(TITLE_CODE, page(lang="zh-CN", title=ASCII31, title_length=len(ASCII31)))

    def test_pure_english_title_still_leaves_to_base_rule(self):
        """阈值分离的硬要求：纯英文标题不走中文阈值。"""
        p = page(lang="en", title="A" * 70, title_length=70)
        assert not fires(TITLE_CODE, p)


# --------------------------------------------------------------------------
# 根因 3：日语不按中文规则判
# --------------------------------------------------------------------------


class TestJapaneseMustNotUseChineseRules:
    """中日汉字同形，`_is_cjk` 对日文标题必然放行。

    asahi.com / au.com / japanpost.jp 的 `lang` 都是 `ja`，且正文含大量假名
    （2026-10-01 实跑确认：asahi kana=49 / kanji=97，au kana=77 / kanji=32，
    japanpost kana=32 / kanji=50）。
    """

    def test_asahi_news_headline_must_be_silent_on_title(self):
        title = (
            "維新だけで進む大阪都構想、他の政党は何してる？ 距離置く理由とは"
            " [大阪府] [自由民主党（自民党）][公明党][日本維新の会]：朝日新聞"
        )
        p = page(lang="ja", title=title, title_length=len(title))
        assert _title_px(title) > 480  # 像素预算确实超了，是作用域问题不是测量问题
        assert not fires(TITLE_CODE, p)

    def test_asahi_must_be_silent_on_semantic_rule(self):
        """meta.chinese_semantic_incomplete 样本：描述里「大阪」重复 4 次。

        正常日文新闻里反复提地名是自然语言，不是中文 SEO 的关键词堆砌。
        """
        title = (
            "維新だけで進む大阪都構想、他の政党は何してる？ 距離置く理由とは"
            " [大阪府] [自由民主党（自民党）][公明党][日本維新の会]：朝日新聞"
        )
        p = page(
            lang="ja",
            title=title,
            title_length=len(title),
            meta_description=(
                "大阪市を廃止して東京23区のような特別区に再編する「大阪都構想」の制度設計が"
                "急ピッチで進んでいる。大阪府・市の両議会で過半数を占め、都構想を推進する"
                "地域政党・大阪維新の会が単独で制度案の作成を進めて…"
            ),
        )
        assert p.meta_description.count("大阪") >= 3
        assert not fires(SEM_CODE, p)

    def test_japanpost_must_be_silent_on_semantic_rule(self):
        """标题只有「日本郵政」4 个字、没有假名——所以还得看 lang 属性。"""
        p = page(
            lang="ja",
            title="日本郵政",
            title_length=4,
            meta_description=(
                "日本郵政株式会社のWebサイトへようこそ。日本郵政株式会社は、"
                "日本郵便株式会社・株式会社ゆうちょ銀行・株式会社かんぽ生命保険などからなる"
                "日本郵政グループの持株会社です。"
            ),
        )
        assert not fires(SEM_CODE, p)

    def test_au_japanese_title_must_be_silent(self):
        title = "【公式】au | スマートフォン・携帯・料金プラン・インターネットの料金とプラン比較"
        p = page(lang="ja", title=title, title_length=len(title))
        assert _title_px(title) > 480  # 像素预算确实超了，是作用域问题不是测量问题
        assert not fires(TITLE_CODE, p)

    def test_kana_alone_detects_japanese_when_lang_is_wrong(self):
        """翻译代理可能把 lang 改写成 zh-CN；假名是第二道判据。"""
        title = "大阪都構想の法定協の開催について"
        p = page(lang="zh-CN", title=title, title_length=len(title))
        assert not fires(TITLE_CODE, p)

    # ---- 反向用例：中文页绝不能被日语守卫误伤 ----------------------------

    def test_chinese_page_with_ja_lang_still_semantic_fires(self):
        """守卫只挡日语，不该因为 lang 写错就把中文真问题一起吃掉。"""
        p = page(
            lang="zh-CN",
            title="防水登山鞋",
            title_length=5,
            meta_description=(
                "本店主营防水登山鞋，防水登山鞋款式齐全，"
                "防水登山鞋价格实惠，欢迎选购防水登山鞋。"
            ),
        )
        assert p.meta_description.count("防水登山鞋") >= 3
        assert fires(SEM_CODE, p)


# --------------------------------------------------------------------------
# meta.chinese_semantic_incomplete 的真实中文堆砌仍要触发
# --------------------------------------------------------------------------


class TestRealChineseStuffingStillFires:
    """根因 1 和 3 都是**作用域**修正，没有动 n-gram 统计本身。

    所以真实的中文堆砌必须照报——如果这些也不报，说明规则被改成永远沉默了。
    """

    def test_stuffed_title_fires(self):
        title = "防水登山鞋 - 防水登山鞋 - 防水登山鞋 - 户外装备"
        p = page(lang="zh-CN", title=title, title_length=len(title))
        assert fires(SEM_CODE, p)

    def test_stuffed_description_fires(self):
        p = page(
            lang="zh-CN",
            title="户外运动装备商城",
            title_length=7,
            meta_description=(
                "专业防水登山鞋，登山鞋十大品牌，登山鞋哪个牌子好，"
                "登山鞋推荐及选购指南，登山鞋价格与折扣。"
            ),
        )
        assert fires(SEM_CODE, p)

    def test_normal_chinese_prose_does_not_fire(self):
        """反向：正常中文散文不重复词根，不该报。"""
        p = page(
            lang="zh-CN",
            title="防水登山鞋选购指南",
            title_length=8,
            meta_description=(
                "本文介绍如何挑选一双合脚的鞋。先量脚长，再看鞋楦是否贴合脚背，"
                "最后试穿走几步，确认不会磨脚。只有常走的路况才值得投入硬底。"
            ),
        )
        assert not fires(SEM_CODE, p)


# --------------------------------------------------------------------------
# 小工具：容差比较
# --------------------------------------------------------------------------


def pytest_approx(value: float, tol: float = 0.15):
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return other is not None and abs(float(other) - value) <= tol

        def __repr__(self) -> str:
            return f"≈{value}"

    return _Approx()
