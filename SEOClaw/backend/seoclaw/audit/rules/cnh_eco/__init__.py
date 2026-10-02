"""中文生态扩展检查项包（market = Market.CNH_ECO）。

覆盖百度之外的渠道：微信/搜一搜等。这里只放**能被证据判定**的规则——
渠道策略类结论除非能指出具体证据，否则不输出，宁可少做。

评估后**未实现**的候选（结论记录在案，避免以后重复评估）：

- `nap.entity_inconsistent`（页脚公司名/地址/电话跨页不一致）
  做不了，原因有三：① 页脚被正文抽取器（trafilatura）剥掉，拿到的 page.text
  里根本没有页脚；② 页脚里的品牌名/加盟商/子公司名天然不一致，无法区分
  「NAP 不一致」与「多主体运营」；③ 同一页面出现两个电话号码是正常的
  （总机 + 售后）。要做得准，需要提取层先保留 footer_text / footer_links，
  属于跨模块改动，超出本包范围。
- 微信分享卡片（og:title/og:image）缺失：Page 模型目前没有 og:* 字段，
  规则层看不到，分享卡片问题无法检测。
"""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlparse

from ....models import Issue, Market, Page, Scope, Severity
from ....util import cjk_ratio, contains_han
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()

# 微信生态的官方域名
WECHAT_HOSTS = ("mp.weixin.qq.com", "weixin.qq.com", "channels.weixin.qq.com")


# ⚠️ 技术债 #3：同上，此处只看汉字（contains_han）。
# 收进谚文会让韩语站被判成「中文站」，进而触发微信生态规则。
def _is_cjk(text: str) -> bool:
    return contains_han(text)


def _chinese_page_ratio(pages: list[Page]) -> tuple[float, int]:
    scored = 0
    total = 0
    for p in pages:
        if p.status_code != 200 or not p.is_html or p.error:
            continue
        total += 1
        text = p.text or p.title or ""
        if (p.lang or "").lower().startswith("zh") or (
            text and cjk_ratio(text) > 0.2
        ):
            scored += 1
    if not total:
        return 0.0, 0
    return scored / total, total


@reg.register
class SogouWechatNotIndexable(Rule):
    code = "wechat.sogou_not_indexable"
    market = Market.CNH_ECO
    severity = Severity.INFO
    scope = Scope.SITE
    title = "微信搜一搜不索引站外页面：微信渠道需单独运营"
    description = (
        "微信搜一搜（及搜狗的微信搜索）的内容来自公众号/视频号生态，"
        "**不会像百度那样收录站外网页**。也就是说：一个再好的官网，"
        "在微信里搜品牌词时也不会自然出现。"
        "这条不是网站的技术缺陷，而是渠道策略提醒——"
        "想让内容进入微信生态，需要公众号/小程序/视频号这样的载体，"
        "再从官网往那里导流。"
        "⚠️ 判定基于「站内没有任何指向微信生态的链接」，"
        "如果你们本来就在别处运营公众号，这条属于误报，请忽略。"
    )
    fix_hint = (
        "开通公众号或视频号，把官网核心内容做成微信内的固定入口；"
        "官网页脚/关于页放上公众号二维码与名称，"
        "让搜品牌词的用户和微信里的内容互相导流。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ★ 数据充分性门槛：结论是「全站没看到微信入口」，
        #   属于靠「没看到」下结论，必须先确认大部分页面都抓到了。
        if not ctx.has_enough_data():
            return

        pages = [p for p in ctx.all_pages if p.status_code == 200 and p.is_html and not p.error]
        if not pages:
            return

        zh_ratio, total = _chinese_page_ratio(ctx.all_pages)
        # 站点内容根本不是中文：不需要微信渠道，不提
        if zh_ratio < 0.5:
            return

        hits: list[dict[str, Any]] = []
        for p in pages:
            for link in p.links:
                host = urlparse(link.href).netloc.lower()
                if any(host == h or host.endswith("." + h) for h in WECHAT_HOSTS):
                    hits.append({"page_url": p.url, "target": link.href, "anchor": link.anchor})

        if hits:
            # 已经有微信生态入口 → 渠道没问题，保持沉默
            return

        yield self._site_issue(
            ctx,
            {
                "domain": ctx.domain,
                "pages_checked": total,
                "wechat_links_found": 0,
                "chinese_page_ratio": round(zh_ratio, 3),
                "coverage": round(ctx.coverage, 3),
                "verdict": "no_wechat_channel_detected",
                "verdict_explain": (
                    f"{zh_ratio:.0%} 的页面是中文内容，说明目标用户很可能在微信里搜索；"
                    f"但扫描 {total} 页（覆盖率 {ctx.coverage:.0%}）后，"
                    "没有发现任何指向 mp.weixin.qq.com / weixin.qq.com 的链接。"
                    "注意：公众号二维码是图片、入口可能放在弹窗或 JS 里，"
                    "所以这是策略提醒而非判定——若你们已有公众号运营，忽略本条。"
                ),
                "channel_note": (
                    "搜一搜收录的是公众号/视频号内的内容，官网无法被直接索引；"
                    "官网在这条链路上的作用是「承接导流 + 沉淀品牌词」。"
                ),
            },
        )
