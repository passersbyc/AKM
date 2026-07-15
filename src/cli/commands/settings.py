import argparse
import json
from pathlib import Path
from src.cli.core import BaseCommand
from src.core.config import get_project_root
from src.core.registry import _reset_id_registry


_SETTABLE_KEYS = ["library_path", "db_path",
                  "convert_traditional", "migrate_mode",
                  "download_file_path", "max_workers", "timeout",
                  "follow_max_workers", "rate_limit_rps",
                  "image_rate_limit_rps",
                  "pull_base_csv",
                  "log.level", "log.file.format", "log.file.datefmt",
                  "log.file.encoding", "log.file.max_bytes",
                  "log.file.backup_count", "log.console.format",
                  "log.console.show_time", "log.console.show_level",
                  "log.console.show_path", "log.console.markup"]

# Keys that live in config["download"] rather than config["project_settings"]
_DOWNLOAD_KEYS = {"max_workers", "timeout", "follow_max_workers",
                  "rate_limit_rps", "image_rate_limit_rps",
                  "retry_429", "retry_429_delay_seconds",
                  "retry_429_max_workers"}
# Keys that live at config top level
_TOP_KEYS = {"download_file_path"}
# Keys that live under config["log"] — value is the sub-path list
_LOG_KEYS = {
    "log.level": ["log", "level"],
    "log.file.format": ["log", "file", "format"],
    "log.file.datefmt": ["log", "file", "datefmt"],
    "log.file.encoding": ["log", "file", "encoding"],
    "log.file.max_bytes": ["log", "file", "max_bytes"],
    "log.file.backup_count": ["log", "file", "backup_count"],
    "log.console.format": ["log", "console", "format"],
    "log.console.show_time": ["log", "console", "show_time"],
    "log.console.show_level": ["log", "console", "show_level"],
    "log.console.show_path": ["log", "console", "show_path"],
    "log.console.markup": ["log", "console", "markup"],
}

# Keys whose values should be coerced to int
_INT_KEYS = {"log.file.max_bytes", "log.file.backup_count"}
# Keys whose values should be coerced to bool
_BOOL_KEYS = {"log.console.show_time", "log.console.show_level",
              "log.console.show_path", "log.console.markup"}

_RESET_DEFAULTS = {
    "library_path": "library",
    "db_path": "data/library.db",
    "convert_traditional": True,
    "migrate_mode": "copy",
    "download_file_path": "downloads",
    "max_workers": 10,
    "timeout": 10,
    "follow_max_workers": 3,
    "rate_limit_rps": 2.0,
    "image_rate_limit_rps": 6.0,
    "pull_base_csv": "",
    "log.level": "INFO",
    "log.file.format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "log.file.datefmt": "",
    "log.file.encoding": "utf-8",
    "log.file.max_bytes": 10 * 1024 * 1024,
    "log.file.backup_count": 5,
    "log.console.format": "%(message)s",
    "log.console.show_time": False,
    "log.console.show_level": False,
    "log.console.show_path": False,
    "log.console.markup": True,
}
_DEFAULT_FILETYPE = {
    "txt": "小说", "epub": "小说", "mobi": "小说", "azw3": "小说",
    "docx": "小说", "doc": "小说",
    "jpg": "图片", "jpeg": "图片", "png": "图片", "gif": "图片",
    "pdf": "漫画", "zip": "漫画",
    "mp4": "电影", "avi": "电影", "mkv": "电影",
    "mp3": "音乐", "flac": "音乐", "wav": "音乐",
}


class SettingsCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "settings"

    @property
    def description(self) -> str:
        return "查看或修改项目设置"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        subparsers = parser.add_subparsers(dest="action", help="操作类型")

        show_parser = subparsers.add_parser("show", help="显示当前设置")

        set_parser = subparsers.add_parser("set", help="修改 project_settings 中的设置项")
        set_parser.add_argument("key", choices=_SETTABLE_KEYS, help="设置项名称")
        set_parser.add_argument("value", type=str, help="设置项新值")

        reset_parser = subparsers.add_parser("reset", help="重置设置为默认值")
        reset_parser.add_argument("key", nargs="?", choices=_SETTABLE_KEYS,
                                  help="要重置的设置项（不指定则重置所有）")

        ft_parser = subparsers.add_parser("filetype", help="管理文件类型映射")
        ft_sub = ft_parser.add_subparsers(dest="ft_action", help="文件类型操作")

        ft_add = ft_sub.add_parser("add", help="添加文件类型映射")
        ft_add.add_argument("ext", help="扩展名（不含点，如 mp4）")
        ft_add.add_argument("category", help="分类名（如 电影）")

        ft_rm = ft_sub.add_parser("rm", help="删除文件类型映射")
        ft_rm.add_argument("ext", help="扩展名")

        ft_reset = ft_sub.add_parser("reset", help="重置文件类型映射为默认值")

        ft_list = ft_sub.add_parser("list", help="列出所有文件类型映射")

        cookie_parser = subparsers.add_parser("cookie", help="管理平台鉴权信息")
        cookie_sub = cookie_parser.add_subparsers(dest="cookie_action", help="鉴权操作")

        cookie_set = cookie_sub.add_parser("set", help="设置 Pixiv refresh_token")
        cookie_set.add_argument("platform", choices=["pixiv"], help="目标平台")
        cookie_set.add_argument("value", type=str, help="refresh_token 字符串")

        cookie_show = cookie_sub.add_parser("show", help="查看已设置的鉴权信息（脱敏显示）")

        cookie_clear = cookie_sub.add_parser("clear", help="清除平台鉴权信息")
        cookie_clear.add_argument("platform", nargs="?", choices=["pixiv"],
                                  help="要清除的平台（不指定则清除所有）")

    def _load_config(self) -> dict:
        config_path = get_project_root() / "config.json"
        if not config_path.exists():
            return {}
        return json.loads(config_path.read_text(encoding="utf-8"))

    def _save_config(self, config: dict) -> None:
        config_path = get_project_root() / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=4),
                               encoding="utf-8")

    def _get_value(self, config: dict, key: str):
        if key in _LOG_KEYS:
            return self._get_nested(config, _LOG_KEYS[key])
        if key in _DOWNLOAD_KEYS:
            return config.get("download", {}).get(key)
        elif key in _TOP_KEYS:
            return config.get(key)
        return config.get("project_settings", {}).get(key)

    def _set_value(self, config: dict, key: str, value) -> None:
        if key in _LOG_KEYS:
            self._set_nested(config, _LOG_KEYS[key], value)
            return
        if key in _DOWNLOAD_KEYS:
            config.setdefault("download", {})[key] = value
        elif key in _TOP_KEYS:
            config[key] = value
        else:
            config.setdefault("project_settings", {})[key] = value

    @staticmethod
    def _get_nested(config: dict, path: list[str]):
        d = config
        for i, segment in enumerate(path):
            if i == len(path) - 1:
                return d.get(segment)
            d = d.setdefault(segment, {})
        return None

    @staticmethod
    def _set_nested(config: dict, path: list[str], value) -> None:
        d = config
        for i, segment in enumerate(path):
            if i == len(path) - 1:
                d[segment] = value
                return
            d = d.setdefault(segment, {})

    def execute(self, args: argparse.Namespace) -> int:
        config = self._load_config()
        if not config:
            self._print_error("配置文件不存在")
            return 1

        settings = config.get("project_settings", {})

        if args.action == "show":
            filetypes = config.get("filetype", {})
            download_cfg = config.get("download", {})
            log_cfg = config.get("log", {})
            if self._json_mode:
                return self._respond(True, {
                    "project_settings": settings,
                    "download": download_cfg,
                    "download_file_path": config.get("download_file_path"),
                    "filetype": filetypes,
                    "log": log_cfg,
                })

            self._print("[bold]project_settings:[/bold]")
            for k, v in settings.items():
                self._print(f"  {k}: {v}")
            if config.get("download_file_path"):
                self._print(f"  download_file_path: {config['download_file_path']}")
            self._print("")
            self._print("[bold]download:[/bold]")
            for k, v in download_cfg.items():
                self._print(f"  {k}: {v}")
            self._print("")
            self._print("[bold]log:[/bold]")
            self._print(f"  level: {log_cfg.get('level', 'INFO')}")
            file_cfg = log_cfg.get("file", {})
            for k, v in file_cfg.items():
                self._print(f"  file.{k}: {v}")
            console_cfg = log_cfg.get("console", {})
            for k, v in console_cfg.items():
                self._print(f"  console.{k}: {v}")
            self._print("")
            self._print("[bold]filetype:[/bold]")
            for ext, cat in sorted(filetypes.items()):
                self._print(f"  .{ext} → {cat}")
            return 0

        elif args.action == "set":
            old_value = self._get_value(config, args.key)
            if args.key == "convert_traditional" or args.key in _BOOL_KEYS:
                new_val = args.value.lower() in ("true", "1", "yes", "on")
            elif args.key in _INT_KEYS:
                try:
                    new_val = int(args.value)
                except ValueError:
                    self._print_error(f"无效的值（需要整数）: {args.value}")
                    return 1
            elif args.key in _DOWNLOAD_KEYS | {"max_workers", "timeout", "follow_max_workers"} | _LOG_KEYS.keys():
                try:
                    if args.key in ("max_workers", "timeout", "follow_max_workers", "retry_429_max_workers") or args.key in _INT_KEYS:
                        new_val = int(args.value)
                    elif args.key in ("rate_limit_rps", "image_rate_limit_rps"):
                        new_val = float(args.value)
                    else:
                        new_val = args.value
                except ValueError:
                    self._print_error(f"无效的值: {args.value}")
                    return 1
            else:
                new_val = args.value
            self._set_value(config, args.key, new_val)
            self._save_config(config)
            self._print(f"[green]已更新 {args.key}: {old_value} -> {new_val}[/green]")
            return 0

        elif args.action == "reset":
            if args.key:
                if args.key in _RESET_DEFAULTS:
                    old_value = self._get_value(config, args.key)
                    new_val = _RESET_DEFAULTS[args.key]
                    self._set_value(config, args.key, new_val)
                    self._save_config(config)
                    self._print(f"[green]已重置 {args.key}: {old_value} -> {new_val}[/green]")
                else:
                    self._print_error(f"不支持重置的键: {args.key}")
                    return 1
            else:
                config["project_settings"] = {
                    k: v for k, v in _RESET_DEFAULTS.items()
                    if k not in _DOWNLOAD_KEYS and k not in _TOP_KEYS and k not in _LOG_KEYS
                }
                config["download"] = {
                    k: v for k, v in _RESET_DEFAULTS.items()
                    if k in _DOWNLOAD_KEYS
                }
                for k, v in _RESET_DEFAULTS.items():
                    if k in _TOP_KEYS:
                        config[k] = v
                    elif k in _LOG_KEYS:
                        self._set_nested(config, _LOG_KEYS[k], v)
                self._save_config(config)
                _reset_id_registry()
                self._print("[green]已重置所有设置为默认值[/green]")
            return 0

        elif args.action == "filetype":
            filetypes = config.setdefault("filetype", {})
            ft_action = getattr(args, "ft_action", None)

            if ft_action == "add":
                ext = args.ext.lower().lstrip(".")
                if not ext:
                    self._print_error("扩展名不能为空")
                    return 1
                if args.category in ("add", "rm", "reset", "list"):
                    self._print_error(f"'{args.category}' 是保留关键词，不能用作分类名")
                    return 1
                filetypes[ext] = args.category
                config["filetype"] = filetypes
                self._save_config(config)
                self._print(f"[green]已添加 .{ext} → {args.category}[/green]")
                return 0

            elif ft_action == "rm":
                ext = args.ext.lower().lstrip(".")
                if ext in filetypes:
                    cat = filetypes.pop(ext)
                    self._save_config(config)
                    self._print(f"[green]已删除 .{ext} → {cat}[/green]")
                else:
                    self._print(f"[yellow].{ext} 不在映射中[/yellow]")
                return 0

            elif ft_action == "reset":
                config["filetype"] = _DEFAULT_FILETYPE.copy()
                self._save_config(config)
                self._print("[green]已重置文件类型映射为默认值[/green]")
                return 0

            elif ft_action == "list" or ft_action is None:
                if self._json_mode:
                    return self._respond(True, {"filetype": filetypes})
                if not filetypes:
                    self._print("[yellow]文件类型映射为空[/yellow]")
                else:
                    self._print("[bold]文件类型映射:[/bold]")
                    from rich.table import Table
                    table = Table(show_header=True, header_style="bold")
                    table.add_column("扩展名", style="cyan")
                    table.add_column("分类", style="green")
                    for ext, cat in sorted(filetypes.items()):
                        table.add_row(f".{ext}", cat)
                    self._print(table)
                return 0

            else:
                self._print_error("请指定 filetype 操作: add / rm / reset / list")
                return 1

        elif args.action == "cookie":
            cookie_action = getattr(args, "cookie_action", None)

            if cookie_action == "set":
                config.setdefault("pixiv", {})["refresh_token"] = args.value
                self._save_config(config)
                self._print(f"[green]已设置 pixiv refresh_token[/green]")
                return 0

            elif cookie_action == "show":
                pixiv_token = (config.get("pixiv", {}) or {}).get("refresh_token", "")
                if self._json_mode:
                    return self._respond(True, {
                        "pixiv_has_refresh_token": bool(pixiv_token),
                    })
                if pixiv_token:
                    masked = pixiv_token[:20] + "..." if len(pixiv_token) > 20 else pixiv_token
                    self._print(f"[bold]已设置的鉴权信息:[/bold]\n  pixiv (refresh_token): {masked}")
                else:
                    self._print("[yellow]未设置任何鉴权信息[/yellow]")
                return 0

            elif cookie_action == "clear":
                config.setdefault("pixiv", {})["refresh_token"] = ""
                self._save_config(config)
                self._print("[green]已清除 pixiv refresh_token[/green]")
                return 0

            else:
                self._print_error("请指定操作: set / show / clear")
                return 1

        else:
            self._print_error("请指定操作: show / set / reset / filetype / cookie")
            return 1
