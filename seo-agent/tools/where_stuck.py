#!/usr/bin/env python3
"""抓 energy.gov 扫描卡死处的调用栈。

背景
----
sitemap 递归的无界漏洞已修（SITEMAP_TIME_BUDGET + MAX_CHILD_ATTEMPTS），
SitemapFinder.discover 现在 25 秒返回、不再卡死。但**整次扫描仍是 0 字节**，
说明卡的不止 sitemap 一处。之前用 kill -ABRT 拿栈失败，是因为没给进程
装 faulthandler 定时器——SIGABRT 只在 Python 字节码之间才响应，卡在
C 扩展里（lxml / httpx）就哑了。

dump_traceback_later 是可靠做法：到点由解释器自己从任何位置 dump，
不依赖信号送达。
"""
import faulthandler
import sys
import threading

# 35 秒后自动打栈到 stderr，之后每 20 秒再打一次，方便看它是卡死还是慢
faulthandler.dump_traceback_later(35, repeat=True, exit=False)

sys.argv = [
    "app.cli", "scan", "https://www.energy.gov/",
    "--max-pages", "5", "--rps", "1.5", "--no-verify-canonical", "--json",
]

from app.cli import main  # noqa: E402

threading.Thread(target=lambda: None, daemon=True).start()
main()
