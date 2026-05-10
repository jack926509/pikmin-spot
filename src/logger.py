import json
import logging
import sys
from typing import Any

from src.config import settings


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _BoundLogger:
    def __init__(self, base: logging.Logger):
        self._base = base

    def _emit(self, level: int, msg: str, **kw: Any) -> None:
        self._base.log(level, msg, extra=kw)

    def debug(self, msg: str, **kw: Any) -> None: self._emit(logging.DEBUG, msg, **kw)
    def info(self, msg: str, **kw: Any) -> None: self._emit(logging.INFO, msg, **kw)
    def warning(self, msg: str, **kw: Any) -> None: self._emit(logging.WARNING, msg, **kw)
    def error(self, msg: str, **kw: Any) -> None: self._emit(logging.ERROR, msg, **kw)
    def exception(self, msg: str, **kw: Any) -> None:
        self._base.exception(msg, extra=kw)


_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())
    _configured = True


def get_logger(name: str) -> _BoundLogger:
    _configure_root()
    return _BoundLogger(logging.getLogger(name))
