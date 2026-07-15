import logging
import re
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List


_RICH_MARKUP_PATTERN = re.compile(r"\[/?[a-z][a-z #,\-]*\]")


class MarkupStrippingFormatter(logging.Formatter):
    """文件 handler 专用 formatter：剥离 Rich 标记后输出纯文本。"""

    def format(self, record: logging.LogRecord) -> str:
        record = logging.makeLogRecord(vars(record))
        record.msg = _RICH_MARKUP_PATTERN.sub("", str(record.msg))
        if record.args:
            record.msg = record.msg % record.args
            record.args = None
        return super().format(record)


def _get_data_dir() -> Path:
    from src.core.config import get_data_dir

    return get_data_dir()


def _load_log_config() -> dict:
    try:
        from src.core.config import load_config

        cfg = load_config()
        return cfg.get("log", {})
    except Exception:
        return {}


_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_BACKUP_COUNT = 5

_DEFAULT_FILE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DEFAULT_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S %z"
_DEFAULT_CONSOLE_FORMAT = "%(message)s"

_console_handlers: List[logging.Handler] = []


def setup_logging(level: Optional[int] = None, *, reset: bool = False) -> None:
    """初始化日志系统（在加载 config 后调用一次即可）。"""
    global _console_handlers
    log_config = _load_log_config()

    if level is None:
        level_str = log_config.get("level", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

    root = logging.getLogger("akm")
    root.setLevel(level)
    root.propagate = False

    if root.hasHandlers():
        if not reset:
            return
        root.handlers.clear()

    # --- 文件 handler（带轮转） ---
    file_cfg = log_config.get("file", {})
    log_path = _get_data_dir() / "application.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=file_cfg.get("max_bytes", _DEFAULT_MAX_BYTES),
        backupCount=file_cfg.get("backup_count", _DEFAULT_BACKUP_COUNT),
        encoding=file_cfg.get("encoding", "utf-8"),
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = file_cfg.get("format", _DEFAULT_FILE_FORMAT)
    file_datefmt = file_cfg.get("datefmt") or _DEFAULT_FILE_DATEFMT
    file_handler.setFormatter(MarkupStrippingFormatter(file_fmt, datefmt=file_datefmt))
    root.addHandler(file_handler)

    # --- 控制台 handler（Rich） ---
    console_cfg = log_config.get("console", {})
    _console_handlers.clear()
    try:
        from rich.logging import RichHandler
        from rich.console import Console

        console_handler = RichHandler(
            rich_tracebacks=True,
            show_path=console_cfg.get("show_path", False),
            show_time=console_cfg.get("show_time", False),
            show_level=console_cfg.get("show_level", False),
            markup=console_cfg.get("markup", True),
            console=Console(stderr=True),
        )
        console_handler.setLevel(level)
        console_fmt = console_cfg.get("format", _DEFAULT_CONSOLE_FORMAT)
        console_handler.setFormatter(logging.Formatter(console_fmt))
        root.addHandler(console_handler)
        _console_handlers.append(console_handler)
    except ImportError:
        fallback = logging.StreamHandler()
        fallback.setLevel(level)
        fallback.setFormatter(logging.Formatter(console_cfg.get("format", _DEFAULT_CONSOLE_FORMAT)))
        root.addHandler(fallback)
        _console_handlers.append(fallback)

    # 可配置的第三方模块噪声抑制
    suppress_cfg = log_config.get("suppress", [])
    for item in suppress_cfg:
        name = item.get("name")
        lvl = getattr(logging, item.get("level", "ERROR").upper(), logging.ERROR)
        if name:
            logging.getLogger(name).setLevel(lvl)

    # 无配置时使用默认抑制
    if not suppress_cfg:
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


def set_level(level: int | str) -> None:
    """运行时动态调整 akm 及其控制台 handler 的日志级别。

    文件 handler 始终为 DEBUG，确保全量写入文件。
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("akm")
    root.setLevel(level)
    for handler in _console_handlers:
        handler.setLevel(level)


def get_logger(name: str = "akm") -> logging.Logger:
    """获取具名 logger，自动继承 ``akm`` 根的 handler。"""
    return logging.getLogger(name)


logger: logging.Logger = logging.getLogger("akm")
