"""结构化日志收口。

## 为什么单独一层

服务端排障靠日志，而本项目此前全靠 ``print(file=sys.stderr)``——CLI 里
可以接受，进了 FastAPI 服务就是灾难：没有级别、没有时间戳、没法按模块
过滤、没法被采集。``api/scan_service.py`` 里甚至有一段「同步统计算完直接
丢弃，因为这个文件没有 logger」的注释——观测断档就是这么来的。

## 用法

模块顶部一行::

    log = logging.getLogger(__name__)

进程启动时调一次 :func:`configure`（``main.py`` 的 lifespan 里）。不调也
能用——只是没有统一格式与级别控制，退化为 logging 默认输出。

## 输出形状

- ``text``（默认）：给人看，``时间 级别 模块: 消息``
- ``json``：给采集器看，一行一个 JSON，``extra=`` 字段并进顶层便于检索

切换用环境变量 ``SEO_CLAW_LOG_FORMAT=json`` / ``SEO_CLAW_LOG_LEVEL=DEBUG``，
不改代码。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

#: LogRecord 自带字段名单。``extra=`` 传进来的并进 JSON 顶层，
#: 这些自带的不重复输出（message/asctime 是 format 阶段才生成的）。
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """一行一个 JSON 对象，给日志采集（Loki / CloudWatch / 自建）用。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = val
        # default=str：extra 里混进 datetime/Path 之类的对象不该让整条日志炸掉
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure(level: str | None = None, fmt: str | None = None) -> None:
    """配置根 logger。幂等：重复调用只替换 handler，不叠加。

    ⚠️ 级别/格式参数优先于环境变量，都不给才用默认值——测试里可以
    ``configure(level="DEBUG")`` 而不必污染环境。
    """
    # str(...) 兜底：mypy 对 `a or b or c` 的类型收窄到这里就散了，
    # 而两个入口参数都是 Optional[str]。
    lvl = str(level or os.getenv("SEO_CLAW_LOG_LEVEL") or "INFO").upper()
    fmt = str(fmt or os.getenv("SEO_CLAW_LOG_FORMAT") or "text").lower()

    root = logging.getLogger()
    root.setLevel(getattr(logging, lvl, logging.INFO))
    for old in list(root.handlers):
        root.removeHandler(old)

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    root.addHandler(handler)
