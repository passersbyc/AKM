import argparse
import os
import shutil
from pathlib import Path

from src.cli.core import BaseCommand
from src.core.logging import logger
from src.core.config import get_project_root, get_library_path
from src.operations import read_all_entries, clean_delete_entries


class CleanCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "clean"

    @property
    def description(self) -> str:
        return "清理项目中的临时文件、缓存、日志、空目录"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("-l", "--library", action="store_true", help="清理库文件（清空 library 目录）")
        parser.add_argument("-w", "--works", action="store_true", help="清理作品清单数据")
        parser.add_argument("-e", "--empty-dirs", action="store_true", help="递归清理空目录")
        parser.add_argument("-g", "--logs", action="store_true", help="清理日志文件 (*.log)")
        parser.add_argument("-a", "--all", action="store_true", help="清除所有内容（库、清单、缓存、日志、空目录）")
        parser.add_argument("-d", "--deep", action="store_true",
                            help="深度检查：验证清单完整性、检查游离文件")
        parser.add_argument("--rm-orphans", action="store_true",
                            help="深度检查时自动删除游离文件（库中存在但清单未记录的文件）")
        parser.add_argument("--fix-missing", action="store_true",
                            help="深度检查时自动从清单中移除文件已丢失的记录")
        parser.add_argument("--rm-empty-dirs", action="store_true",
                            help="深度检查时自动删除空文件夹")
        parser.add_argument("-q", "--query", type=str, default=None,
                            help="指定清理操作的目标路径（默认项目根目录）")
        parser.add_argument("-f", "--force", action="store_true", help="强制清理，跳过确认提示")

    def execute(self, args: argparse.Namespace) -> int:
        if args.force:
            self._no_confirm = True

        root_path = Path(args.query) if args.query else get_project_root()
        if not root_path.is_dir():
            if not root_path.exists():
                try:
                    root_path.mkdir(parents=True)
                except Exception:
                    pass

        if args.deep:
            self._deep_check(args, root_path,
                            args.fix_missing, args.rm_orphans, args.rm_empty_dirs)
            return 0

        if args.all:
            self._clean_all(root_path)
            return 0

        performed = False

        if args.library:
            self._clean_library()
            performed = True

        if args.works:
            self._clean_works()
            performed = True

        if args.logs:
            self._clean_logs(root_path)
            performed = True

        if args.empty_dirs:
            self._clean_empty_dirs(root_path)
            performed = True

        if not performed:
            self._print("[yellow]未指定清理目标，默认执行缓存清理。使用 -h 查看更多选项。[/yellow]")

        self._clean_cache(root_path)

        return 0

    def _deep_check(self, args: argparse.Namespace, root_path: Path,
                    fix_missing: bool, rm_orphans: bool, rm_empty_dirs: bool) -> None:
        self._print("[cyan]正在执行深度检查...[/cyan]")

        library_path = get_library_path()

        rows = read_all_entries()

        if not rows:
            self._print("[yellow]清单为空[/yellow]")
        else:
            no_path_count = 0
            missing_count = 0
            present_count = 0

            for row in rows:
                file_path_str = row.get("文件路径", "").strip()
                if not file_path_str:
                    no_path_count += 1
                    self._print(f"[yellow]  缺少文件路径 [ID: {row.get('ID', '?')}, 标题: {row.get('标题', '?')}][/yellow]")
                    continue

                fp = Path(file_path_str)
                if not fp.exists():
                    missing_count += 1
                    self._print(f"[yellow]  缺失: {row.get('标题', '?')} [ID: {row.get('ID', '?')}] {file_path_str}[/yellow]")
                else:
                    present_count += 1

            self._print(f"\n[bold]检查结果:[/bold] 总计 {len(rows)} 条 — "
                        f"[green]完好 {present_count}[/green]"
                        + (f", [yellow]缺失 {missing_count}[/yellow]" if missing_count else "")
                        + (f", [yellow]无路径 {no_path_count}[/yellow]" if no_path_count else ""))

            if missing_count > 0:
                if fix_missing:
                    invalid_ids = set()
                    for row in rows:
                        fp_str = row.get("文件路径", "").strip()
                        if not fp_str or not Path(fp_str).exists():
                            invalid_ids.add(row.get("ID", ""))
                    if invalid_ids and self._confirm(f"确认从清单中移除 {len(invalid_ids)} 条无效记录？"):
                        clean_delete_entries(invalid_ids)
                        self._print(f"[green]已移除 {len(invalid_ids)} 条无效记录[/green]")
                    else:
                        self._print("已取消")
                else:
                    self._print("[dim]使用 --fix-missing 可从清单中移除这些无效记录[/dim]")

        if library_path.exists():
            self._print(f"\n[bold]检查书库: {library_path}[/bold]")
            self._check_library_orphans(library_path, rm_orphans)
            self._check_empty_dirs_in_library(library_path, rm_empty_dirs)

    def _check_library_orphans(self, library_path: Path,
                                remove_orphans: bool) -> None:
        manifest_files: set = set()
        try:
            for row in read_all_entries():
                fp_str = row.get("文件路径", "").strip()
                if fp_str:
                    fp = Path(fp_str)
                    manifest_files.add(fp.resolve())
        except Exception:
            pass

        orphans: list = []
        for file_path in library_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith('.'):
                if file_path.resolve() not in manifest_files:
                    orphans.append(file_path)

        if orphans:
            self._print(f"[yellow]发现 {len(orphans)} 个游离文件（库中存在但清单未记录）[/yellow]")
            for fp in orphans:
                self._print(f"  [dim]{fp}[/dim]")
            if remove_orphans:
                if self._confirm(f"确认删除这 {len(orphans)} 个游离文件吗？此操作不可恢复"):
                    deleted = 0
                    for fp in orphans:
                        try:
                            fp.unlink()
                            deleted += 1
                        except Exception as e:
                            self._print(f"[red]删除失败 {fp}: {e}[/red]")
                    self._print(f"[green]已删除 {deleted} 个游离文件[/green]")
                else:
                    self._print("已取消删除游离文件")
            else:
                self._print("[dim]使用 --rm-orphans 可自动删除这些文件[/dim]")
        else:
            self._print("[green]未发现游离文件[/green]")

    def _check_empty_dirs_in_library(self, library_path: Path,
                                      remove_empty: bool) -> None:
        empty_dirs: list = []
        for dirpath, dirnames, filenames in os.walk(library_path, topdown=False):
            if ".git" in dirpath or ".venv" in dirpath:
                continue
            try:
                p = Path(dirpath)
                if p != library_path and not any(p.iterdir()):
                    empty_dirs.append(p)
            except Exception:
                pass

        if empty_dirs:
            self._print(f"\n[bold]检查空文件夹:[/bold]")
            self._print(f"[yellow]发现 {len(empty_dirs)} 个空文件夹[/yellow]")
            for d in sorted(empty_dirs):
                self._print(f"  [dim]{d}[/dim]")
            if remove_empty:
                if self._confirm(f"确认删除这 {len(empty_dirs)} 个空文件夹？"):
                    deleted = 0
                    for d in sorted(empty_dirs, reverse=True):
                        try:
                            d.rmdir()
                            deleted += 1
                        except Exception as e:
                            self._print(f"[red]删除失败 {d}: {e}[/red]")
                    self._print(f"[green]已删除 {deleted} 个空文件夹[/green]")
                else:
                    self._print("已取消")
            else:
                self._print("[dim]使用 --rm-empty-dirs 可自动删除这些空文件夹[/dim]")
        else:
            self._print(f"\n[bold]检查空文件夹:[/bold]")
            self._print("[green]未发现空文件夹[/green]")

    def _clean_library(self) -> None:
        library_path = get_library_path()
        if not library_path.exists():
            self._print(f"[yellow]库目录不存在: {library_path}[/yellow]")
            return

        if self._confirm(f"确认清空整个书库 {library_path} 吗？所有图书文件将被删除"):
            deleted_count = 0
            for item in library_path.iterdir():
                if item.name == ".meta":
                    continue
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    deleted_count += 1
                except Exception as e:
                    self._print_error(f"删除 {item.name} 失败: {e}")

            if deleted_count > 0:
                self._print(f"[green]书库已清空，共删除 {deleted_count} 个项目[/green]")
            else:
                self._print("[green]书库已是空的[/green]")
        else:
            self._print("已取消")

    def _clean_works(self) -> None:
        if self._confirm("确认清空所有作品清单记录吗？"):
            try:
                from src.core.database import get_db
                db = get_db()
                with db:
                    db.execute("DELETE FROM works")
                self._print("[green]已清空作品清单[/green]")
            except Exception as e:
                self._print_error(f"清空清单失败: {e}")
        else:
            self._print("已取消")

    def _clean_logs(self, root_path: Path) -> None:
        targets = ["*.log", "*.log.*"]
        found_items: set = set()

        for pattern in targets:
            try:
                found_items.update(root_path.glob(pattern))
                project_root = get_project_root()
                if root_path != project_root:
                    found_items.update(project_root.glob(pattern))
            except Exception:
                continue

        if not found_items:
            self._print("[green]未发现日志文件[/green]")
            return

        if self._confirm(f"确认删除 {len(found_items)} 个日志文件？"):
            deleted = 0
            for item in found_items:
                try:
                    item.unlink()
                    deleted += 1
                except Exception as e:
                    self._print(f"[yellow]无法删除 {item.name}（可能正在使用中）: {e}[/yellow]")
            self._print(f"[green]已删除 {deleted} 个日志文件[/green]")
        else:
            self._print("已取消")

    def _clean_empty_dirs(self, root_path: Path) -> None:
        self._print(f"[dim]正在扫描空目录 (在 {root_path})...[/dim]")
        deleted_count = 0

        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
            if ".git" in dirpath or ".venv" in dirpath or "__pycache__" in dirpath:
                continue
            try:
                p = Path(dirpath)
                if not any(p.iterdir()):
                    p.rmdir()
                    deleted_count += 1
            except Exception:
                pass

        if deleted_count > 0:
            self._print(f"[green]已清理 {deleted_count} 个空目录[/green]")
        else:
            self._print("[green]未发现空目录[/green]")

    def _clean_cache(self, root_path: Path) -> None:
        targets = ["__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".pytest_cache"]
        found_items: set = set()

        for pattern in targets:
            try:
                found_items.update(root_path.rglob(pattern))
            except Exception:
                continue

        if not found_items:
            self._print("[green]缓存已是最干净的状态[/green]")
            return

        sorted_items = sorted(found_items, key=lambda p: len(p.parts), reverse=True)
        cleaned_count = 0
        for item in sorted_items:
            if not item.exists():
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                cleaned_count += 1
            except Exception as e:
                self._print(f"[dim]跳过 {item.name}: {e}[/dim]")

        if cleaned_count > 0:
            self._print(f"[green]缓存清理完成，共清理 {cleaned_count} 处[/green]")

    def _clean_all(self, root_path: Path) -> None:
        self._print("[yellow]即将执行全量清理...[/yellow]")
        if not self._no_confirm:
            if not self._confirm("确认执行全量清理？此操作不可逆"):
                self._print("已取消")
                return
            self._no_confirm = True

        self._clean_library()
        self._clean_works()
        self._clean_logs(root_path)
        self._clean_cache(root_path)
        self._clean_empty_dirs(root_path)
        self._print("[green]全量清理完成[/green]")
