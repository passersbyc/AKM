"""统一输出层 — 替代旧 BaseCommand 的 _respond/_print/_print_error/_print_info/_print_warning。

json 模式：结构化数据输出到 stdout，人类提示输出到 stderr。
文本模式：Rich console 渲染表格/面板，降级到 logger。
"""
import json as _json
import sys
from typing import Any, Optional

from src.core.logging import logger


class Output:
    def __init__(self, json_mode: bool = False, no_confirm: bool = False):
        self._json_mode = json_mode
        self._no_confirm = no_confirm
        self._console = None

    @property
    def console(self):
        if self._console is None:
            try:
                from rich.console import Console
                self._console = Console(stderr=True)
            except ImportError:
                self._console = None
        return self._console

    def set_flags(self, json_mode: bool, no_confirm: bool) -> None:
        self._json_mode = json_mode
        self._no_confirm = no_confirm

    @property
    def json_mode(self) -> bool:
        return self._json_mode

    @property
    def no_confirm(self) -> bool:
        return self._no_confirm

    def result(self, success: bool, data: Any = None,
               error: Optional[str] = None, exit_code: Optional[int] = None) -> int:
        if self._json_mode:
            payload = {"success": success}
            if data is not None:
                payload["data"] = data
            if error:
                payload["error"] = error
            print(_json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if success else (exit_code if exit_code is not None else 1)
        if error and not success:
            logger.error(error)
        return exit_code if exit_code is not None else (0 if success else 1)

    def table(self, title: str, columns: list[dict], rows: list[list[Any]],
              footer: Optional[str] = None) -> None:
        if self._json_mode:
            keys = [c["key"] for c in columns]
            data = [dict(zip(keys, r)) for r in rows]
            print(_json.dumps({"title": title, "rows": data}, ensure_ascii=False, indent=2))
            return
        if self.console:
            from rich.table import Table
            t = Table(title=title, show_lines=False)
            for c in columns:
                t.add_column(
                    c["header"],
                    style=c.get("style"),
                    justify=c.get("justify"),
                    no_wrap=c.get("no_wrap", False),
                    width=c.get("width"),
                    max_width=c.get("max_width"),
                )
            for r in rows:
                t.add_row(*[str(x) if x is not None else "" for x in r])
            self.console.print(t)
            if footer:
                self.console.print(f"[dim]{footer}[/dim]")
        else:
            logger.info(title)
            headers = [c["header"] for c in columns]
            logger.info("  ".join(headers))
            for r in rows:
                logger.info("  ".join(str(x) for x in r))
            if footer:
                logger.info(footer)

    def info(self, message: str) -> None:
        if self._json_mode:
            print(message, file=sys.stderr)
        elif self.console:
            self.console.print(message)
        else:
            logger.info(message)

    def warn(self, message: str) -> None:
        if self._json_mode:
            print(f"WARNING: {message}", file=sys.stderr)
        else:
            logger.warning(message)

    def error(self, message: str) -> None:
        if self._json_mode:
            print(message, file=sys.stderr)
        else:
            logger.error(message)

    def print(self, *args, **kwargs) -> None:
        if self._json_mode:
            print(*args, file=sys.stderr, **kwargs)
        elif self.console:
            self.console.print(*args, **kwargs)
        else:
            logger.info(" ".join(str(a) for a in args))

    def confirm(self, message: str) -> bool:
        if self._no_confirm:
            return True
        while True:
            response = input(f"{message} [y/n]: ").strip().lower()
            if response in ("y", "yes"):
                return True
            if response in ("n", "no"):
                return False
            print("请输入 y 或 n。")
