"""搜索结果标题的字符像素宽度表 —— google / baidu 两个市场包共用。

为什么单独一个模块（这是个有事故记录的技术债，见 PLAN.md「已知技术债」）：

    baidu 包曾经**整段复制** google 包的宽度表，因为 `from ..google import`
    会构成环引用（google.i18n → google → baidu → google），实测导致规则
    注册表加载失败、29 个测试全红。复制的代价是两处表必须人工保持同步，
    注释里写着「改 google 必须同步这里」——这种约定迟早会被漏掉。

    环引用的根因是「共用常量住在某个市场包里」。把常量上提到一个**不
    import 任何规则包**的中立模块后，谁引它都不会成环，同步债就此消除。

数字口径（16px 基准无衬线 UI 字体的平均字宽，误差 ±10% 以内）：
足够区分「明显超标」和「安全区」，不追求像素级精确——Google/百度用的
都是可变字体，本来也算不出精确值。判定逻辑（误差带、预算阈值）留在各
市场包自己手里：两家的截断宽度和容错策略不同，不该强行统一。
"""

from __future__ import annotations

# 半角字符宽度（px）。
W_NARROW = set("iljItf.,;:'!|()[]-·’‘“”\"`")  # ≈4.5px
W_UPPER = 10.7
W_LOWER = 8.0
W_DIGIT = 8.9
W_SPACE = 4.4
W_PUNCT = 5.5
W_OTHER_ALPHA = 9.0  # 西里尔、希腊等
W_EMOJI = 16.0  # emoji 按 1em 全宽渲染，当成标点算会窄一半

# 中英文弯引号。ASCII 的 ' " 确实窄，但 “”‘’ 在 CJK 字体里是全角
# （=1em）。按窄引号算会低估约 3.5px/个（真实样本：discourse 的中文标题）。
CURLY_QUOTES = set("“”‘’")
W_CURLY_NARROW = 4.5
W_CURLY_FULL = 16.0

# 一个 em = 16px（CJK 全角定宽字符的字宽）
W_EM = 16.0


def is_zero_width(cp: int) -> bool:
    """变体选择符 / ZWJ：只影响相邻 glyph 形状，本身不占宽度。"""
    return cp == 0x200D or 0xFE00 <= cp <= 0xFE0F


def is_emoji_cp(cp: int) -> bool:
    """emoji / 符号类区块。这些字符实际渲染都接近全角。"""
    return (
        0x1F000 <= cp <= 0x1FAFF  # 各类 pictograph、emoji
        or 0x2600 <= cp <= 0x27BF  # 杂项符号、装饰符号（✓★❤…）
        or 0x2B00 <= cp <= 0x2BFF  # 补充箭头/星号
        or 0x1F1E6 <= cp <= 0x1F1FF  # 区域指示符（国旗）
    )
