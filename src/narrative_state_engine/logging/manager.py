from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from narrative_state_engine.logging.config import (
    LOG_COLORIZE,
    LOG_COMPRESSION,
    LOG_DIR,
    LOG_FILE,
    LOG_JSON,
    LOG_LEVEL,
    LOG_MAX_MESSAGE_CHARS,
    LOG_RETENTION,
    LOG_ROTATION,
)
from narrative_state_engine.logging.context import context_filter

try:  # pragma: no cover
    from loguru import logger as loguru_logger
except ModuleNotFoundError:  # pragma: no cover
    loguru_logger = None


class LogManager:
    _inited = False

    @classmethod
    def init(cls):
        if cls._inited:
            return cls.get_logger()

        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        if loguru_logger is not None:
            cls._init_loguru()
        else:
            cls._init_stdlib()
        cls._inited = True
        return cls.get_logger()

    @classmethod
    def _init_loguru(cls) -> None:  # pragma: no cover
        logfile = str(Path(LOG_DIR) / LOG_FILE)
        loguru_logger.remove()
        loguru_logger.configure(patcher=cls._patch_record)
        fmt = cls._fmt(json=LOG_JSON)
        loguru_logger.add(
            logfile,
            level=LOG_LEVEL.upper(),
            backtrace=False,
            diagnose=False,
            rotation=LOG_ROTATION,
            retention=LOG_RETENTION,
            compression=LOG_COMPRESSION,
            enqueue=True,
            filter=context_filter,
            serialize=LOG_JSON,
            format=None if LOG_JSON else fmt,
            colorize=False,
        )
        loguru_logger.add(
            sys.stdout,
            level=LOG_LEVEL.upper(),
            backtrace=False,
            diagnose=False,
            filter=context_filter,
            serialize=False,
            format=fmt,
            colorize=False,
        )

    @classmethod
    def _init_stdlib(cls) -> None:
        logger = logging.getLogger("narrative_state_engine")
        logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
        logger.handlers.clear()
        formatter = logging.Formatter(
            "%(asctime)s | %(ctx)s%(levelname)s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%y-%m-%d %H:%M:%S",
        )
        file_handler = logging.FileHandler(Path(LOG_DIR) / LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        logger.propagate = False

        class ContextFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                payload: dict[str, Any] = {
                    "extra": {},
                    "message": record.getMessage(),
                    "level": {"name": record.levelname},
                }
                context_filter(payload)
                extra = payload["extra"]
                record.ctx = cls._build_ctx(extra)
                if LOG_MAX_MESSAGE_CHARS and len(record.msg if isinstance(record.msg, str) else str(record.msg)) > LOG_MAX_MESSAGE_CHARS:
                    record.msg = str(record.msg)[:LOG_MAX_MESSAGE_CHARS] + "\n...[truncated]"
                return True

        logger.addFilter(ContextFilter())

    @staticmethod
    def _build_ctx(extra: dict[str, Any]) -> str:
        parts = []
        for label, key in (
            ("rid", "request_id"),
            ("tid", "thread_id"),
            ("story", "story_id"),
            ("actor", "actor"),
            ("action", "action"),
        ):
            value = extra.get(key)
            if value not in (None, ""):
                parts.append(f"{label}={value}")
        return (" ".join(parts) + " | ") if parts else ""

    @classmethod
    def _patch_record(cls, record: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        extra = record["extra"]
        message = record["message"]
        if isinstance(message, str) and LOG_MAX_MESSAGE_CHARS and len(message) > LOG_MAX_MESSAGE_CHARS:
            record["message"] = message[:LOG_MAX_MESSAGE_CHARS] + "\n...[truncated]"
        extra["ctx"] = cls._build_ctx(extra)
        if LOG_COLORIZE:
            ansi_map = {
                "TRACE": "\033[37m",
                "DEBUG": "\033[34m",
                "INFO": "\033[32m",
                "SUCCESS": "\033[32m",
                "WARNING": "\033[33m",
                "ERROR": "\033[31m",
                "CRITICAL": "\033[1;31m",
            }
            extra["color_prefix"] = ansi_map.get(record["level"].name, "\033[36m")
            extra["color_reset"] = "\033[0m"
        else:
            extra["color_prefix"] = ""
            extra["color_reset"] = ""
        return record

    @staticmethod
    def _fmt(*, json: bool) -> str:  # pragma: no cover
        if json:
            return "{message}\n"
        return (
            "{extra[color_prefix]}"
            "{time:YY-MM-DD HH:mm:ss.SSS} | "
            "{extra[ctx]}{level} | "
            "{name}:{function}:{line} - "
            "{message}"
            "{extra[color_reset]}"
        )

    @classmethod
    def get_logger(cls):
        if loguru_logger is not None:  # pragma: no cover
            return loguru_logger
        return logging.getLogger("narrative_state_engine")


def init_logging():
    return LogManager.init()


def get_logger():
    return LogManager.init()
