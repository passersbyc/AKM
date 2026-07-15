"""声明式 BaseCommand — 替代旧 cli/core.py 的 BaseCommand。

支持三种 verb 形态：
  类型 A: verb + noun + args   (list work, info work)
  类型 B: verb + args (无 noun) (import <path>, stats)
  类型 C: verb only            (stats)

子类只需声明 verb / nouns 类属性，并实现 configure_parser / configure_noun_parser / execute。
框架（CLIApp）自动构建 verb→noun 两级 subparser。
"""
import abc
import argparse
import json
from typing import ClassVar, Optional

from src.cli.output import Output
from src.core.config import get_project_root, translate_error
from src.core.logging import logger


class BaseCommand(abc.ABC):
    verb: ClassVar[str] = ""
    nouns: ClassVar[list[str]] = []
    description: ClassVar[str] = ""

    def __init__(self):
        self.config = self._load_config()
        library_rel = self.config.get("project_settings", {}).get("library_path", "library")
        self.library_path = get_project_root() / library_rel
        self._ensure_db()
        self.output = Output()

    def set_flags(self, json_mode: bool, no_confirm: bool) -> None:
        self.output.set_flags(json_mode, no_confirm)

    @property
    def console(self):
        return self.output.console

    def _ensure_db(self):
        from src.core.database import init_db
        init_db()

    def _load_config(self) -> dict:
        try:
            config_path = get_project_root() / "config.json"
            if config_path.exists():
                return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"无法加载配置文件 config.json，使用默认配置。错误信息：{translate_error(e)}")
            return {}
        return {}

    def _save_config(self, config: dict) -> None:
        config_path = get_project_root() / "config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")

    # ── 子类必须实现的接口 ──────────────────────────────────

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """配置 verb 级参数。verb-only 命令在此配置全部参数。"""
        pass

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        """配置 verb→noun 二级参数。仅当 nouns 非空时需实现。"""
        pass

    @abc.abstractmethod
    def execute(self, args: argparse.Namespace, noun: Optional[str] = None) -> int:
        """执行命令。noun 为 None 表示 verb-only 命令。"""
        ...
