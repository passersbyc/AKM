import argparse
import subprocess
import webbrowser
from pathlib import Path

from src.cli.base import BaseCommand
from src.operations.matcher import resolve_work, resolve_author
from src.core.logging import logger


class OpenCommand(BaseCommand):
    verb = "open"
    nouns = ["url"]
    description = "在关联应用中打开作品文件，或打开来源网址"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target", type=str, help="作品 ID 或名称")

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        if noun == "url":
            parser.add_argument("target", type=str,
                                help="作品 ID/名称 或 作者 ID/名称")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "url":
            return self._open_url(args)
        return self._open_file(args)

    def _open_file(self, args: argparse.Namespace) -> int:
        work = resolve_work(args.target, self.output)
        if not work:
            return self.output.result(False, error=f"未找到作品: {args.target}")

        fp = Path(work.get("file_path", "").strip() or "")
        if not fp.exists():
            return self.output.result(False, error=f"文件不存在: {fp}")

        try:
            subprocess.run(["open", str(fp)])
        except Exception as e:
            return self.output.result(False, error=f"打开失败: {e}")

        logger.info(f"已打开: {fp.name}")
        self._record_open(work["id"], work.get("title", ""))

        if self.output.json_mode:
            return self.output.result(True, data={
                "id": work["id"],
                "title": work.get("title", ""),
                "file_path": str(fp),
                "work": self._work_json(work),
            })

        self._show_work_info(work)
        return 0

    def _show_work_info(self, work: dict) -> None:
        """以 Rich 面板展示作品元数据。"""
        try:
            from rich.table import Table
            from rich.panel import Panel
            from rich.text import Text
            from src.core.database import short_id
        except ImportError:
            return

        from src.operations import get_related_works

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("字段", style="cyan", width=10, no_wrap=True)
        table.add_column("值", style="white", overflow="fold")
        likes = work.get("likes", 0) or 0
        rating = work.get("rating", 0) or 0
        for k, v in [
            ("ID", short_id(work["id"])),
            ("标题", work.get("title", "")),
            ("作者", self._author_name(work.get("author_id", ""))),
            ("系列", self._series_name(work.get("series_id", ""), work.get("author_id", ""))),
            ("标签", work.get("tags", "") or "-"),
            ("来源", work.get("source", "") or "-"),
            ("分类", work.get("file_type", "未知")),
            ("文件大小", f"{round(work.get('file_size_kb', 0) or 0, 1)} KB"),
            ("导入时间", work.get("imported_at", "")),
            ("收藏", "♥" if work.get("favorite") else ""),
            ("点赞", str(likes) if likes > 0 else ""),
            ("评分", str(rating) if rating > 0 else ""),
        ]:
            table.add_row(k, str(v))
        self.console.print(Panel(
            table,
            title=f"[bold green]{work.get('标题', '')}[/bold green]",
            subtitle=f"[dim]ID: {work['id']}[/dim]",
        ))
        desc = (work.get("description", "") or "").strip()
        if desc:
            self.console.print(Panel(Text(desc), title="[bold]简介[/bold]"))

        series = (work.get("series_id", "") or "").strip()
        if series:
            related = get_related_works(series, exclude_id=work["id"])
            if related:
                rel_table = Table(title=f"同系列 ({len(related)})")
                rel_table.add_column("ID", style="dim", width=10)
                rel_table.add_column("标题", style="green")
                for r in related[:5]:
                    rel_table.add_row(short_id(r.get("ID", "")), r.get("标题", ""))
                self.console.print(rel_table)

    @staticmethod
    def _author_name(author_id: str) -> str:
        if not author_id:
            return "未知"
        from src.core.database import get_db
        row = get_db().execute("SELECT name FROM authors WHERE id = ?", (author_id,)).fetchone()
        return row["name"] if row else author_id

    @staticmethod
    def _series_name(series_id: str, author_id: str) -> str:
        if not series_id:
            return "-"
        from src.core.database import get_db
        row = get_db().execute(
            "SELECT name FROM series WHERE id = ? AND author_id = ?",
            (series_id, author_id),
        ).fetchone()
        return row["name"] if row else series_id

    @staticmethod
    def _work_json(work: dict) -> dict:
        from src.core.database import short_id
        return {
            "ID": work["id"],
            "短ID": short_id(work["id"]),
            "标题": work.get("title", ""),
            "作者": OpenCommand._author_name(work.get("author_id", "")),
            "系列": OpenCommand._series_name(work.get("series_id", ""), work.get("author_id", "")),
            "标签": work.get("tags", "") or "",
            "来源": work.get("source", "") or "",
            "分类": work.get("file_type", ""),
            "文件大小(KB)": round(work.get("file_size_kb", 0) or 0, 1),
            "导入时间": work.get("imported_at", ""),
            "收藏": "是" if work.get("favorite") else "否",
            "点赞": work.get("likes", 0) or 0,
            "评分": work.get("rating", 0) or 0,
            "简介": work.get("description", "") or "",
            "文件路径": work.get("file_path", "") or "",
        }

    def _open_url(self, args: argparse.Namespace) -> int:
        target = args.target

        # 先尝试匹配作品
        work = resolve_work(target, self.output)
        if work:
            source = (work.get("source", "") or "").strip()
            if source and source.startswith("http"):
                webbrowser.open(source)
                logger.info(f"已打开: {source}")
                if self.output.json_mode:
                    return self.output.result(True, data={"id": work["id"], "url": source})
                return 0
            if source == "local" or not source:
                return self.output.result(False, error=f"作品 {work.get('title', '')} 无来源网址")

        # 再尝试匹配作者
        author = resolve_author(target, self.output)
        if author:
            homepage = (author.get("homepage", "") or "").strip()
            if homepage and homepage.startswith("http"):
                webbrowser.open(homepage)
                logger.info(f"已打开: {homepage}")
                if self.output.json_mode:
                    return self.output.result(True, data={"author_id": author["id"], "url": homepage})
                return 0
            return self.output.result(False, error=f"作者 {author.get('name', '')} 无网址")

        return self.output.result(False, error=f"未找到作品或作者: {target}")

    def _record_open(self, work_id: str, title: str) -> None:
        try:
            from src.core.database import get_db
            db = get_db()
            db.execute(
                "INSERT INTO recent_opens (work_id, title) VALUES (?, ?)",
                (work_id, title),
            )
            db.execute(
                "DELETE FROM recent_opens WHERE id NOT IN "
                "(SELECT id FROM recent_opens ORDER BY opened_at DESC LIMIT 50)"
            )
            db.commit()
        except Exception:
            pass
