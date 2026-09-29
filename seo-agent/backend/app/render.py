"""
JS 渲染层：用 Playwright 执行页面 JS 后取回渲染后的 HTML。

为什么需要它（实测踩出来的坑）
------------------------------
go.dev 是 Next.js 站点，静态 HTML 里几乎没有 <a> 标签，链接全部由客户端
渲染。我们的爬虫从首页只发现了 1 个 URL，站内 600+ 页面完全抓不到——
对一个 SEO 工具来说这是致命的功能缺失，因为搜索引擎同样需要执行 JS。

设计上刻意做成「可选 + 优雅降级」
--------------------------------
浏览器二进制可能没装、可能下载失败、可能启动慢。任何一种情况都不该让
整个工具不可用——降级回静态 HTML，并在结果里标记「该页未渲染」，
让上层规则知道证据强度不足。工具的可用性永远优先于功能完整性。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RenderConfig:
    """渲染行为配置。默认值偏保守，避免把机器跑满。"""

    enabled: bool = False  # 默认关闭：装浏览器要几百 MB，得用户主动开
    timeout_ms: int = 20_000
    wait_until: str = "networkidle"  # domcontentloaded 最快，networkidle 更准但更慢
    wait_selector: Optional[str] = None  # 等待某个元素出现，适合自定义 SPA
    settle_ms: int = 500  # networkidle 后再等一会，给懒加载留时间
    max_html_bytes: int = 5 * 1024 * 1024
    block_resources: tuple[str, ...] = ("image", "media", "font")


class RenderUnavailable(RuntimeError):
    """浏览器不可用。调用方应捕获并降级，而不是让整个扫描失败。"""


class Renderer:
    """同步 Playwright 渲染器。

    浏览器实例是**重量级且非线程安全**的，所以：
      - 进程内单例 + 锁串行访问；
      - 只在真正需要渲染时才启动浏览器，静态抓取零开销。
    """

    _instance: Optional["Renderer"] = None
    _instance_lock = threading.Lock()

    # Playwright 实例必须是**进程级唯一**，不是 Renderer 实例级。
    # ⚠️ 踩过的坑：sync_playwright().start() 每个进程只能调一次，第二次会报
    # 「using Playwright Sync API inside the asyncio loop」。
    # 浏览器同样是重量级资源，全进程共用一个即可。
    _shared_playwright = None
    _shared_browser = None

    # 容器里 /dev/shm 通常只有 64MB，不加这两个参数 Chromium 会直接崩
    _LAUNCH_ARGS = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]

    def __init__(self, config: Optional[RenderConfig] = None) -> None:
        self.config = config or RenderConfig()
        self._playwright = None
        self._browser = None
        self._lock = threading.Lock()
        self._available: Optional[bool] = None
        self._unavailable_reason: Optional[str] = None
        self.stats = {"rendered": 0, "fallback": 0, "failed": 0}

    # -- 单例 -------------------------------------------------------------

    @classmethod
    def instance(cls, config: Optional[RenderConfig] = None) -> "Renderer":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(config)
            elif config is not None:
                cls._instance.config = config
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """测试用：清掉单例。"""
        with cls._instance_lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                except Exception:  # noqa: BLE001
                    pass
            cls._instance = None

    # -- 可用性 -----------------------------------------------------------

    @property
    def available(self) -> bool:
        """浏览器是否可用。检查成本较高，结果缓存。"""
        if self._available is not None:
            return self._available
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            self._available = False
            self._unavailable_reason = f"playwright 未安装: {exc}"
            return False
        self._available = True
        return True

    @property
    def unavailable_reason(self) -> Optional[str]:
        return self._unavailable_reason

    # -- 生命周期 ---------------------------------------------------------

    def _launch(self):
        """启动浏览器，逐个尝试候选可执行文件。

        为什么需要回退：Playwright 包要求的 Chromium build 与机器上已下载的
        build 经常对不上（实测：装的是 1234，Playwright 1.5x 要 1243），
        此时默认启动必然失败。但机器上往往已经有可用的 Chrome——
        重新下载几百 MB 浏览器不该是「让工具能跑」的代价。
        试错顺序：Playwright 自带 → 其它 playwright build → 系统 Chrome。

        ⚠️ 必须复用 self._playwright（已在 _ensure_browser 里 start 过），
        不能在这里再 sync_playwright().chromium.launch(...)：
        后者拿到的是一个**从未 start 的新实例**，launch 必然抛错。
        这个 bug 真的踩过，表现为「加了系统 Chrome 回退，渲染仍然 unavailable」。
        """
        if self._playwright is None:
            raise RenderUnavailable("playwright 实例未启动")

        candidates: list[Optional[str]] = [None]  # None = 用 Playwright 自带
        cache = Path.home() / ".cache" / "ms-playwright"
        if cache.is_dir():
            for d in sorted(cache.glob("chromium-*"), reverse=True):
                for sub in ("chrome-linux64/chrome", "chrome-linux/chrome"):
                    p = d / sub
                    if p.is_file():
                        candidates.append(str(p))
        for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
            p = Path("/usr/bin") / name
            if p.is_file():
                candidates.append(str(p))

        last_err: Optional[Exception] = None
        for exe in candidates:
            try:
                if exe is None:
                    return self._playwright.chromium.launch(args=self._LAUNCH_ARGS)
                return self._playwright.chromium.launch(
                    executable_path=exe, args=self._LAUNCH_ARGS
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        self._unavailable_reason = (
            f"浏览器启动失败（试过 {len(candidates)} 个可执行文件，"
            f"最后一个错误：{last_err}）"
        )
        self._available = False
        raise RenderUnavailable(self._unavailable_reason)

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if Renderer._shared_browser is not None:
            self._playwright = Renderer._shared_playwright
            self._browser = Renderer._shared_browser
            return self._browser
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RenderUnavailable(f"playwright 未安装: {exc}") from exc

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._launch()
            Renderer._shared_playwright = self._playwright
            Renderer._shared_browser = self._browser
        except RenderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"浏览器启动失败: {exc}"
            self._available = False
            raise RenderUnavailable(self._unavailable_reason) from exc
        return self._browser

    def close(self) -> None:
        with self._lock:
            for closer in (self._browser, self._playwright):
                try:
                    if closer is not None:
                        closer.close() if hasattr(closer, "close") else closer.stop()
                except Exception:  # noqa: BLE001
                    pass
            self._browser = None
            self._playwright = None

    # -- 渲染 -------------------------------------------------------------

    def render(self, url: str) -> tuple[Optional[str], str]:
        """渲染 URL，返回 (渲染后 HTML, 状态)。

        状态取值：'rendered' | 'unavailable' | 'failed' | 'disabled'
        调用方据此决定是否降级，以及要不要在报告里标注「该页未渲染」。

        绝不抛异常——渲染是增强能力，不能让它打断主流程。
        """
        if not self.config.enabled:
            return None, "disabled"
        if not self.available:
            return None, "unavailable"

        with self._lock:
            try:
                browser = self._ensure_browser()
            except RenderUnavailable:
                self.stats["fallback"] += 1
                return None, "unavailable"

            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (compatible; SEOAgentBot/0.1; +https://example.com/bot) "
                        "HeadlessChrome"
                    ),
                    viewport={"width": 1366, "height": 768},
                )
                # 屏蔽图片/字体/媒体：它们不影响 SEO 判定，却占绝大部分带宽和时间
                if self.config.block_resources:
                    blocked = set(self.config.block_resources)
                    context.route(
                        "**/*",
                        lambda route: (
                            route.abort()
                            if route.request.resource_type in blocked
                            else route.continue_()
                        ),
                    )
                page = context.new_page()
                page.goto(url, timeout=self.config.timeout_ms, wait_until=self.config.wait_until)

                if self.config.wait_selector:
                    try:
                        page.wait_for_selector(self.config.wait_selector, timeout=5000)
                    except Exception:  # noqa: BLE001 — 等不到元素不该算失败
                        log.debug("wait_selector 超时: %s", self.config.wait_selector)

                if self.config.settle_ms:
                    page.wait_for_timeout(self.config.settle_ms)

                html = page.content()
                context.close()

                if len(html) > self.config.max_html_bytes:
                    html = html[: self.config.max_html_bytes]
                self.stats["rendered"] += 1
                return html, "rendered"

            except Exception as exc:  # noqa: BLE001
                self.stats["failed"] += 1
                log.warning("渲染失败 %s: %s", url, exc)
                return None, "failed"
