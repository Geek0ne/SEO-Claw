#!/usr/bin/env python3
"""用 CDP 直连 page 级 WebSocket，验「质量与验证」页真的渲染出来了。

⚠️ 为什么不用 --dump-dom / 截图：
  - `--dump-dom` 在 --headless=new 下返回空；old 模式下原样吐出源文件
    —— 两种都证明不了 JS 跑没跑。
  - 截图能出，但当前环境看不了图（视觉模型额度用尽）。

⚠️ 判定标准只看**渲染后才存在的东西**：自检结果行、规则条目、统计块。
它们在源码里是 0，只有 JS 跑过 fetch + render 才会有。

⚠️ Chrome 路径按平台分：Windows 上 Chrome 不在 /opt/google/chrome。
找不到就明说，不静默跳过——静默跳过等于「没验过」却说「验过了」。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099/"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9335

#: 各平台的 Chrome 候选路径。找不到就报出来。
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/opt/google/chrome/chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

#: 探测脚本：进「质量与验证」页，等自检跑完，把渲染后的事实取回来。
PROBE = r"""
(async () => {
  // ⚠️ 必须先导航到质量页再等：自检是进页面就自动跑的，
  // 不等它跑完就去数元素，得到的会是「还没渲染完」的读数。
  location.hash = '#/quality';
  await new Promise(r => setTimeout(r, 3500));
  const q = (s) => document.querySelectorAll(s).length;
  return JSON.stringify({
    ready: document.readyState,
    h1: [...document.querySelectorAll('h1')].map(n => n.textContent.trim()),
    navQuality: !!document.querySelector('#navQuality'),
    tabLabels: [...document.querySelectorAll('.tab')].map(n => n.textContent.trim()),
    // 自检结果行：只有自检跑完并渲染才有
    stRows: q('.st-row'),
    stOk: q('.st-mark.ok'),
    stNo: q('.st-mark.no'),
    // 统计块
    stats: q('.stat'),
    statValues: [...document.querySelectorAll('.stat .v')].map(n => n.textContent.trim()),
    // 说明性 note
    notes: [...document.querySelectorAll('.note')].map(n => n.textContent.trim().slice(0, 60)),
    // 错误盒：出现就说明有接口失败
    errBoxes: q('.err-box'),
    mainLen: (document.querySelector('#main')||{}).innerHTML?.length || 0,
    bg: getComputedStyle(document.body).backgroundColor,
  });
})()
"""

#: 第二个探测：切到「规则目录」页签，验规则条目与可展开判据。
PROBE_RULES = r"""
(async () => {
  const tab = [...document.querySelectorAll('.tab')].find(n => n.textContent.trim() === '规则目录');
  if (!tab) return JSON.stringify({error: '规则目录页签不存在'});
  tab.click();
  await new Promise(r => setTimeout(r, 2000));
  const q = (s) => document.querySelectorAll(s).length;
  // 点第一条规则，验判据面板能展开
  const head = document.querySelector('.rule-head');
  if (head) head.click();
  await new Promise(r => setTimeout(r, 400));
  const body = document.querySelector('.rule-body');
  return JSON.stringify({
    ruleItems: q('.rule-item'),
    ruleCodes: [...document.querySelectorAll('.rcode')].slice(0, 5).map(n => n.textContent.trim()),
    bodyVisible: body ? getComputedStyle(body).display !== 'none' : false,
    bodyLen: body ? body.innerHTML.length : 0,
    errBoxes: q('.err-box'),
  });
})()
"""


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError(
        "找不到 Chrome，候选路径都不存在：\n  " + "\n  ".join(CHROME_CANDIDATES)
    )


def launch() -> subprocess.Popen:
    return subprocess.Popen(
        [
            find_chrome(),
            "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--hide-scrollbars", "--window-size=1440,1200",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={tempfile.mkdtemp()}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def page_ws() -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            with opener.open(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as r:
                tabs = json.load(r)
            for t in tabs:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.3)
    raise RuntimeError("Chrome 没起来或没有 page 目标")


async def main() -> int:
    proc = launch()
    try:
        ws_url = await page_ws()
        async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
            events: list[dict] = []

            async def send(i: int, method: str, params=None) -> dict:
                await ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == i:
                        return r
                    events.append(r)

            await send(1, "Runtime.enable")
            await send(3, "Page.enable")
            # ⚠️ 必须先挂监听再导航：页面加载期的异常只在那一刻抛出。
            await send(4, "Page.navigate", {"url": URL})
            await asyncio.sleep(3.0)          # 等首页 fetch + render
            r = await send(2, "Runtime.evaluate",
                           {"expression": PROBE, "returnByValue": True, "awaitPromise": True})
            val = r.get("result", {}).get("result", {}).get("value")
            if not val:
                print("  ✗ 拿不到探测结果：", json.dumps(r, ensure_ascii=False)[:400])
                return 1
            d = json.loads(val)
            print("── 质量与验证页 ──")
            print(json.dumps(d, ensure_ascii=False, indent=2))

            r2 = await send(5, "Runtime.evaluate",
                            {"expression": PROBE_RULES, "returnByValue": True, "awaitPromise": True})
            val2 = r2.get("result", {}).get("result", {}).get("value")
            d2 = json.loads(val2) if val2 else {"error": "拿不到第二个探测结果"}
            print("\n── 规则目录页签 ──")
            print(json.dumps(d2, ensure_ascii=False, indent=2))

            # 判定：自检行有、结论是「全绿」性质（ok 行远多于 no 行）、
            # 无错误盒、规则目录有条目且判据面板能展开。
            ok = (
                d["h1"] == ["质量与验证"]
                and d["stRows"] > 0
                and d["stNo"] == 0
                and d["errBoxes"] == 0
                and d["mainLen"] > 2000
                and d2.get("ruleItems", 0) > 0
                and d2.get("bodyVisible") is True
                and d2.get("errBoxes") == 0
            )
            print("\n  判定：", "✓ 前端渲染成功" if ok else "✗ 有问题")
            return 0 if ok else 1
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
