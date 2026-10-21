"""log.py —— 结构化日志的最小契约。

锁三件事：JSON 形状、extra 字段并进顶层、configure 幂等。
日志测试很容易写成「调用一次不炸就算过」——那等于没测。
"""

from __future__ import annotations

import json
import logging

from seoclaw.log import JsonFormatter, configure


def test_json_formatter_roundtrip():
    fmt = JsonFormatter()
    rec = logging.LogRecord(
        "seoclaw.test", logging.INFO, __file__, 1, "hello %s", ("x",), None
    )
    rec.site_id = 7  # extra= 字段，应并进 JSON 顶层
    out = json.loads(fmt.format(rec))
    assert out["msg"] == "hello x"
    assert out["level"] == "INFO"
    assert out["logger"] == "seoclaw.test"
    assert out["site_id"] == 7
    assert "ts" in out


def test_json_formatter_survives_odd_extra():
    """extra 里混进不可序列化对象时不能让整条日志炸掉。"""
    fmt = JsonFormatter()
    rec = logging.LogRecord("m", logging.INFO, __file__, 1, "path", (), None)
    rec.when = object()
    out = json.loads(fmt.format(rec))
    assert out["msg"] == "path"


def test_configure_is_idempotent():
    """重复 configure 不叠加 handler——叠加是日志翻倍的头号原因。"""
    configure(level="DEBUG", fmt="json")
    configure(level="DEBUG", fmt="json")
    handlers = [h for h in logging.getLogger().handlers]
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, JsonFormatter)
