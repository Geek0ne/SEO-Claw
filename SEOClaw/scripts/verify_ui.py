#!/usr/bin/env python3
"""用 CDP 直接连 page 级 WebSocket，验前端真的渲染出来了。

⚠️ 为什么不用 --dump-dom / 截图：
  - `--dump-dom` 在 --headless=new 下返回空；old 模式下原样吐出源文件
    （48226 字节，一字节不差）—— 两种都证明不了 JS 跑没跑。
  - 截图能出，但当前环境看不了图（视觉模型额度用尽）。

⚠️ 为什么不用 browser 级 Target.attachToTarget：
  试过，Chrome 在 evaluate 期间直接 ConnectionResetError。改成**直接连
  page 目标的 webSocketDebuggerUrl**，不需要 flatten session，少一层就少
  一层崩的可能。

判定标准只看**渲染后才存在的东西**：#siteList 里的站点按钮、页签数量。
它们在源码里是 0，只有 JS 跑过 fetch + render 才会有。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import urllib.request

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077/"
PORT = 9334

PROBE = r"""
(async () => {
  // 先点第一个站点 —— 有多个站点时主区是「从左边选一个」，
  // 不点就没有页签。我第一版把「tabs=0」当成坏了，其实那是正确行为。
  const first = document.querySelector('#siteList button.site-item');
  if (first) first.click();
  await new Promise(r => setTimeout(r, 2500));
  const q = (s) => document.querySelectorAll(s).length;
  return JSON.stringify({
    ready: document.readyState,
    siteButtons: q('#siteList button.site-item'),
    tabs: q('.tab'),
    tabLabels: [...document.querySelectorAll('.tab')].map(n => n.textContent.trim()),
    mainLen: (document.querySelector('#main')||{}).innerHTML?.length || 0,
    errBoxes: q('.err'),
    ring: q('.ring'),
    stats: q('.stat'),
    prio: q('.prio-i'),
    emptyBoxes: q('.empty'),
    h1: [...document.querySelectorAll('h1')].map(n => n.textContent.trim()),
    domains: [...document.querySelectorAll('.site-item .d')].map(n => n.textContent.trim()),
    bg: getComputedStyle(document.body).backgroundColor,
  });
})()
"""


def launch() -> subprocess.Popen:
    return subprocess.Popen(
        [
            "/opt/google/chrome/chrome",
            "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--hide-scrollbars", "--window-size=1440,1000",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={tempfile.mkdtemp()}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def page_ws() -> str:
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as r:
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
            # 之前是「先导航、后挂」，异常早抛完了，监听什么也收不到 ——
            # 于是我只看到 mainLen=0，却不知道原因。
            await send(4, "Page.navigate", {"url": URL})
            await asyncio.sleep(4.5)          # 等 fetch + render
            r = await send(2, "Runtime.evaluate",
                           {"expression": PROBE, "returnByValue": True, "awaitPromise": True})
            val = r.get("result", {}).get("result", {}).get("value")
            if not val:
                print("  ✗ 拿不到探测结果：", json.dumps(r, ensure_ascii=False)[:400])
                return 1
            d = json.loads(val)
            print(json.dumps(d, ensure_ascii=False, indent=2))
            ok = d["siteButtons"] > 0 and d["tabs"] >= 5 and d["errBoxes"] == 0 and d["mainLen"] > 400
            print("\n  判定：", "✓ 前端渲染成功" if ok else "✗ 有问题")
            return 0 if ok else 1
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))