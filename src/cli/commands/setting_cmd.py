import argparse
import json
import shutil
from pathlib import Path

from src.cli.base import BaseCommand
from src.core.config import get_project_root
from src.core.logging import logger


_EXPORT_FORMATS = ["folder", "zip", "epub"]

_SETTING_KEYS = {
    "export_path": {
        "label": "导出路径",
        "config_key": "export_path",
        "section": "project_settings",
        "prompt": "请输入默认导出路径（留空使用当前目录）",
    },
    "export_format": {
        "label": "导出格式",
        "config_key": "export_format",
        "section": "project_settings",
        "prompt": f"请选择导出格式 ({'/'.join(_EXPORT_FORMATS)})",
        "choices": _EXPORT_FORMATS,
    },
    "library_path": {
        "label": "库路径",
        "config_key": "library_path",
        "section": "project_settings",
        "prompt": "请输入库文件存储路径",
        "migrate": True,  # 支持数据迁移
    },
    "library_db_path": {
        "label": "数据库路径",
        "config_key": "db_path",
        "section": "project_settings",
        "prompt": "请输入 library.db 所在的目录路径（如 data）",
        "migrate": True,
    },
}


class SettingCommand(BaseCommand):
    verb = "setting"
    nouns = list(_SETTING_KEYS.keys()) + ["check"]
    description = "交互式配置项目设置"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def configure_noun_parser(self, parser: argparse.ArgumentParser,
                               noun: str) -> None:
        pass

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "check":
            return self._check()

        if noun not in _SETTING_KEYS:
            nouns = ", ".join(list(_SETTING_KEYS.keys()) + ["check"])
            self.output.info(f"用法: setting <{nouns}>")
            return 1

        return self._interactive_set(noun)

    # ── helpers ─────────────────────────────────────────────

    @staticmethod
    def _normalize_db_path(p: str) -> str:
        if not p:
            return p
        # Already a .db file path
        if p.endswith(".db"):
            return p
        # Directory → append library.db
        return p.rstrip("/") + "/library.db"

    # ── core ───────────────────────────────────────────────

    def _interactive_set(self, noun: str) -> int:
        cfg = _SETTING_KEYS[noun]
        config = self._load_config()

        current = self._get_value(config, cfg)
        label = cfg["label"]

        self.output.info(f"[bold]{label}[/bold]")
        if current:
            self.output.info(f"  当前值: [cyan]{current}[/cyan]")
        else:
            self.output.info(f"  当前值: [dim](未设置)[/dim]")

        if "choices" in cfg:
            self.output.info(f"  可选: [dim]{', '.join(cfg['choices'])}[/dim]")

        try:
            value = input(f"\n{cfg['prompt']}: ").strip()
        except (EOFError, KeyboardInterrupt):
            self.output.info("")
            return 0

        if not value:
            self.output.info("[dim]未修改[/dim]")
            return 0

        if "choices" in cfg:
            value = value.lower()
            if value not in cfg["choices"]:
                self.output.info(f"[red]无效格式: {value}，可选: {', '.join(cfg['choices'])}[/red]")
                return 1

        # ── db_path: 目录自动追加 library.db ─────────────
        if noun == "library_db_path":
            value = self._normalize_db_path(value)
            current = self._normalize_db_path(current)

        # ── 数据迁移 ────────────────────────────────────
        if cfg.get("migrate") and current:
            old_path = self._resolve_path(noun, current)
            new_path = self._resolve_path(noun, value)

            if old_path.exists() and old_path != new_path:
                size = self._dir_size(old_path) if old_path.is_dir() else old_path.stat().st_size
                size_str = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"

                self.output.info(f"\n[yellow]检测到旧路径有数据: {old_path} ({size_str})[/yellow]")
                try:
                    confirm = input("是否将数据迁移到新路径？ [y/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    confirm = "n"

                if confirm in ("y", "yes"):
                    if self._migrate(noun, old_path, new_path):
                        self.output.info(f"[green]迁移完成[/green]")
                    else:
                        self.output.info("[red]迁移失败，请手动处理[/red]")
                        return 1
                else:
                    self.output.info("[dim]跳过迁移[/dim]")

        self._set_value(config, cfg, value)
        self._save_config(config)

        self.output.info(f"[green]已更新 {label}: {value}[/green]")

        if noun in ("library_path", "library_db_path"):
            self.output.info("[yellow]请重启程序以使路径变更生效[/yellow]")

        return 0

    # ── migration ──────────────────────────────────────────

    def _resolve_path(self, noun: str, value: str) -> Path:
        root = get_project_root()
        p = Path(value)
        if p.is_absolute():
            return p
        if noun == "library_path":
            return (root / p).absolute()
        if noun == "library_db_path":
            return (root / p).absolute()
        return p.absolute()

    def _dir_size(self, path: Path) -> int:
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return total

    def _migrate(self, noun: str, old: Path, new: Path) -> bool:
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            if old.is_dir():
                shutil.copytree(old, new, dirs_exist_ok=True)
            else:
                shutil.copy2(old, new)
            return True
        except Exception as e:
            logger.error("迁移失败: %s", e)
            return False

    # ── check ───────────────────────────────────────────────

    def _check(self) -> int:
        from src.operations import check_integrity
        from tqdm import tqdm

        state = {"pbar": None}

        def _cb(event, **kw):
            if event == "start":
                total = kw.get("total", 0)
                if not total:
                    self.output.info("库里空空如也，无需检查")
                    return
                self.output.info(f"检查中... [bold]{total}[/bold] 个作品\n")
                state["pbar"] = tqdm(total=total, desc="检查进度", unit="个",
                                     colour="CYAN")
            elif event == "progress":
                msg = kw.get("msg", "")
                if msg:
                    logger.info(msg)
                if state["pbar"]:
                    state["pbar"].update(1)

        result = check_integrity(progress_callback=_cb)
        if state["pbar"]:
            state["pbar"].close()

        if not result["total"]:
            return 0

        ok = result["ok"]
        queued = result["queued"]
        deleted = result["deleted"]
        cleaned = result["cleaned"]
        total = result["total"]

        self.output.info("")
        self.output.info(f"[bold]检查完成: {total} 作品[/bold]")
        self.output.info(f"  [green]✓ OK:       {ok}[/green]")
        if queued:
            self.output.info(f"  [yellow]⚡ 已入队:    {queued} (将重新下载)[/yellow]")
        if deleted:
            self.output.info(f"  [red]🗑 已删除:    {deleted} (无源可恢复)[/red]")
        if cleaned:
            self.output.info(f"  [dim]🧹 已清理:    {cleaned} (孤立文件)[/dim]")
        if not queued and not deleted and not cleaned:
            self.output.info(f"  [green]全部正常[/green]")
        else:
            total_pending = queued + deleted
            self.output.info(f"\n[dim]共 {total_pending} 项异常，{cleaned} 个孤立文件已清理[/dim]")
            if queued:
                self.output.info("[yellow]运行 pull 重新下载已入队的作品[/yellow]")

        return 0

    def _load_config(self) -> dict:
        config_path = get_project_root() / "config.json"
        if not config_path.exists():
            return {}
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self, config: dict) -> None:
        config_path = get_project_root() / "config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=4),
            encoding="utf-8")

    @staticmethod
    def _get_value(config: dict, cfg: dict):
        section = cfg["section"]
        key = cfg["config_key"]
        if section == "project_settings":
            return config.get("project_settings", {}).get(key, "")
        return config.get(key, "")

    @staticmethod
    def _set_value(config: dict, cfg: dict, value) -> None:
        section = cfg["section"]
        key = cfg["config_key"]
        if section == "project_settings":
            config.setdefault("project_settings", {})[key] = value
        else:
            config[key] = value
