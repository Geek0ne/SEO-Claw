"""Web 前端静态检查：JS 语法与 HTML 结构。

⚠️ 为什么需要这一组：页面的 JS 是**一个 2000 行的内联脚本**，没有构建
步骤、没有 lint、没有类型检查。它坏掉的形态是「浏览器直接不执行」——
**页面白屏，后端接口全好，测试全绿**。

我这次改表格结构（把 ``el("table",{}, el("tr",...))`` 统一成
``table(head, rows)``）就踩了：改完 JS 语法是坏的（少一个右括号），
而**没有任何现有测试能发现它**——``test_web.py`` 测的是接口，
``test_docs_stats.py`` 测的是文档数字，没有一条会去看脚本能不能解析。

所以这里补两条：
1. **JS 能被解析**（用 Node 的话就跑 Node；没有 Node 就退化成
   括号/引号平衡检查，**明说退化**，不静默跳过）。
2. **表格结构合法**（``tr`` 必须在 ``thead``/``tbody`` 里）。

第 2 条查的是 ``tbody`` 数为 0 这类偏差：浏览器会容错渲染，页面看着
好好的，但 ``tbody tr`` 选择器选不到行、表头与数据的样式作用域混在
一起、无障碍语义失效。**截图正常不等于结构对**——我是用 CDP 数 DOM
节点才发现仪表盘的 ``tbody`` 是 0。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "seoclaw" / "web" / "static" / "index.html"


def _page_text() -> str:
    assert PAGE.exists(), f"找不到前端页面：{PAGE}"
    return PAGE.read_text(encoding="utf-8")


def _inline_script(html: str) -> str:
    m = re.search(r"<script>([\s\S]*)</script>", html)
    assert m, "页面里没有内联 <script> —— 提取不到就没法检查"
    return m.group(1)


def _node() -> str | None:
    """找 node 可执行文件。找不到返回 None。"""
    for name in ("node", "node.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def test_inline_script_parses_as_valid_javascript():
    """内联脚本必须能被 JavaScript 解析器接受。

    ⚠️ 这是最基础也最容易丢的一条：改一个大文件里的括号，肉眼很难发现，
    而**后果是整页不执行**。有 node 就用 node 的真解析器；没有 node 时
    退化成括号/引号平衡检查，并在结果里说明用的是哪种检查。
    """
    html = _page_text()
    script = _inline_script(html)

    node = _node()
    if node is None:
        pytest.skip(
            "环境里没有 node，跳过 JS 解析检查。"
            "⚠️ 这是**降级**：本条用例没跑，等于少一道闸。"
        )

    # ⚠️ 必须把**提取出的脚本**喂给 node，不能把整个 HTML 文件喂过去——
    # 那样 node 解析的是 "<!DOCTYPE html>..."，报的错是「Unexpected token '<'」，
    # 与脚本本身无关。第一版就是这么写的，测试红得像页面坏了，其实页面好好的。
    proc = subprocess.run(
        [node, "-e", "const vm=require('vm');"
                      "const src=require('fs').readFileSync(0,'utf8');"
                      "new vm.Script(src,{filename:'inline.js'});"],
        input=script,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        "内联脚本有语法错误，浏览器会整段不执行（页面白屏，接口却全好）：\n"
        + (proc.stderr or proc.stdout)
    )


def test_brackets_are_balanced_in_the_inline_script():
    """括号必须配平（不依赖 node 的兜底检查）。

    ⚠️ 为什么要单独留一条而不只靠 node：CI 环境**可能没有 node**，
    那时上面那条会 skip，而这条仍然有效。

    ⚠️ 这条**只做粗检查**：字符串整段跳过、注释跳过、正则按字面量
    跳过，模板串的 ``${...}`` 插值**整体跳过**（插值内部的括号不算）。
    这会漏掉插值里的语法错，但**不会误报**——而误报比漏报更坏：
    一条天天误报的测试，久了就没人看了。

    ⚠️ 我为此重写过三版：① 不懂正则字面量 ② 把 URL 里的 ``//`` 当行
    注释 ③ 嵌套模板串里 ``${has ? `<line/>` : ""}`` 的两层反引号。
    每一次都是**检查器自己错**，页面好好的。最后一版选择「宁可漏、
    不误报」——真正的语法判定交给 node 的真解析器（上一条用例），
    这里只保证「括号大方向没歪」。
    """
    script = _inline_script(_page_text())

    depth = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    i = 0
    n = len(script)
    prev = ""
    while i < n:
        ch = script[i]
        # —— 注释 ——
        if ch == "/" and i + 1 < n and script[i + 1] == "/":
            while i < n and script[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and script[i + 1] == "*":
            end = script.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        # —— 正则字面量 ——
        if ch == "/" and (prev == "" or prev in "([{,=:;&|?!{}"):
            j = i + 1
            in_class = False
            while j < n:
                c = script[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                elif c == "\n":
                    break
                j += 1
            if j < n and script[j] == "/":
                i = j + 1
                while i < n and script[i].isalpha():
                    i += 1
                prev = "x"
                continue
        # —— 字符串与模板串：整段跳过（含插值）——
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                c = script[i]
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    break
                i += 1
            i += 1
            prev = "x"
            continue
        # —— 普通代码 ——
        if ch in depth:
            depth[ch] += 1
        elif ch in closing:
            depth[closing[ch]] -= 1
            if depth[closing[ch]] < 0:
                pytest.fail(f"多余的右括号 {ch!r}")
        if not ch.isspace():
            prev = ch
        i += 1

    # ⚠️ 只断言「圆括号与方括号必须精确配平」——它们不会出现在字符串里，
    # 所以这个判断是可靠的。花括号允许有偏差（模板串插值被整段跳过）。
    assert depth["("] == 0, f"圆括号不配平：{depth}"
    assert depth["["] == 0, f"方括号不配平：{depth}"


def test_rows_live_in_thead_or_tbody():
    """``tr`` 必须挂在 ``thead``/``tbody`` 里，不能直接挂在 ``table`` 下。

    ⚠️ 浏览器会容错渲染（页面看着正常），但那不符合 HTML 规范：
    ① ``tbody tr`` 选择器选不到行 ② 表头与数据的样式作用域混在一起
    ③ 无障碍的表头关联失效。**「截图正常」不等于「结构对」**。

    这条查的是**源码里的构造方式**（``el("table",...)`` / ``el("tr",...)``
    的直接嵌套），不是运行时 DOM——运行时那层由
    ``scripts/verify_quality_ui.py`` 用 CDP 实测。
    """
    html = _page_text()
    # ⚠️ 先剥掉注释再找：注释里写着「直接 el("table",{}, el("tr",...)) 时…」
    # 这段**说明文字**会被当成真的代码匹配上，于是测试报「有 1 处违规」——
    # 而代码其实早就改干净了。查违规之前得先把「提到违规的说明」排除掉。
    code = re.sub(r"/\*[\s\S]*?\*/", "", html)
    code = re.sub(r"//[^\n]*", "", code)
    # 直接把 tr 塞进 table 的写法：el("table", ... el("tr" ...
    offenders = re.findall(r'el\("table",\s*\{[^)]*\}\s*,\s*el\("tr"', code)
    assert not offenders, (
        f"有 {len(offenders)} 处把 tr 直接挂进 table —— "
        "请改用 table(head, rows) 辅助函数（表头进 thead，数据行进 tbody）"
    )


def test_page_declares_the_quality_navigation_entry():
    """左栏必须有「质量与验证」入口，且它指向一个真实存在的视图。

    ⚠️ 入口在但路由没注册，点进去是空白页——这类失效查中文字面量查不出来。
    """
    html = _page_text()
    assert 'id="navQuality"' in html, "左栏缺少「质量与验证」入口"
    assert "viewQuality" in html, "页面里没有 viewQuality 函数"
    assert 'r.head === "quality"' in html, "路由没接 quality 分支"
