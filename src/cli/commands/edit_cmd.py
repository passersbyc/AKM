import argparse

from src.cli.base import BaseCommand
from src.cli.matcher import resolve_work
from src.core.database import get_db, short_id
from src.core.logging import logger
from src.operations import edit_book


def _author_name(author_id: str) -> str:
    if not author_id:
        return ""
    row = get_db().execute("SELECT name FROM authors WHERE id = ?", (author_id,)).fetchone()
    return row["name"] if row else author_id


def _series_name(series_id: str, author_id: str) -> str:
    if not series_id:
        return ""
    row = get_db().execute(
        "SELECT name FROM series WHERE id = ? AND author_id = ?",
        (series_id, author_id),
    ).fetchone()
    return row["name"] if row else series_id


class EditCommand(BaseCommand):
    verb = "edit"
    nouns: list[str] = []
    description = "交互式编辑作品元数据（逐字段提示）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target", type=str, help="作品 ID 或名称")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        work = resolve_work(args.target, self.output)
        if not work:
            return self.output.result(False, error=f"未找到作品: {args.target}")

        wid = work["id"]
        title = work.get("title", "")
        author_id = work.get("author_id", "")
        series_id = work.get("series_id", "")
        author_name = _author_name(author_id)
        series_name = _series_name(series_id, author_id)
        tags = work.get("tags", "") or ""
        rating = work.get("rating", 0) or 0
        favorite = work.get("favorite", 0)
        description = work.get("description", "") or ""
        likes = work.get("likes", 0) or 0

        if self.output.json_mode:
            return self.output.result(True, data={"work": dict(work)})

        self.output.info(f"\n[bold green]编辑作品:[/bold green] [cyan]{short_id(wid)}[/cyan] {title}\n")

        field_updates: dict[str, str] = {}
        new_author = ""
        new_series = ""

        def _prompt(field_name: str, current_val: str, field_key: str = "") -> None:
            display = current_val if current_val else "(空)"
            try:
                new_val = input(f"  {field_name} [{display}] → ").strip()
            except (EOFError, KeyboardInterrupt):
                new_val = ""
            if new_val:
                field_updates[field_key] = new_val

        _prompt("标题", title, "标题")

        _prompt("作者", author_name, "作者")
        # 作者字段特殊处理：移除 field_updates 中的作者，改用 new_author
        if "作者" in field_updates:
            new_author = field_updates.pop("作者")

        _prompt("系列", series_name, "系列")
        if "系列" in field_updates:
            new_series = field_updates.pop("系列")

        _prompt("标签", tags, "标签")

        # 评分
        try:
            rating_input = input(f"  评分 [{rating}] → ").strip()
        except (EOFError, KeyboardInterrupt):
            rating_input = ""
        if rating_input:
            try:
                r = float(rating_input)
                if 0 <= r <= 10:
                    field_updates["评分"] = str(r) if r > 0 else ""
                else:
                    self.output.info("[yellow]评分需在 0-10 之间，跳过[/yellow]")
            except ValueError:
                self.output.info("[yellow]评分格式无效，跳过[/yellow]")

        # 收藏
        fav_display = "是" if favorite else "否"
        try:
            fav_input = input(f"  收藏 [{fav_display}] (y/n) → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            fav_input = ""
        if fav_input in ("y", "yes"):
            field_updates["收藏"] = "是"
        elif fav_input in ("n", "no"):
            field_updates["收藏"] = "否"

        # 简介
        _prompt("简介", description, "简介")

        # 点赞
        try:
            like_input = input(f"  点赞 [{likes}] → ").strip()
        except (EOFError, KeyboardInterrupt):
            like_input = ""
        if like_input:
            try:
                field_updates["点赞"] = str(int(like_input))
            except ValueError:
                self.output.info("[yellow]点赞数格式无效，跳过[/yellow]")

        if not field_updates and not new_author and not new_series:
            self.output.info("[dim]无修改，退出[/dim]")
            return 0

        # 确认
        try:
            confirm = input("\n确认保存？(y/n) → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = ""
        if confirm not in ("y", "yes"):
            self.output.info("[dim]已取消[/dim]")
            return 0

        updated = edit_book(wid, field_updates,
                            new_author=new_author, new_series=new_series)
        if not updated:
            return self.output.result(False, error=f"更新失败: {wid}")

        self.output.info(f"[green]✓ 已更新:[/green] {updated.get('标题', title)}")
        return 0
