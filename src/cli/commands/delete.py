import argparse
from src.cli.core import BaseCommand
from src.operations import filter_rows, delete_by_ids, delete_authors, delete_series, delete_book, resolve_author_targets


class DeleteCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "delete"

    @property
    def description(self) -> str:
        return "删除作品/作者/系列"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target_type", nargs="?", default="book",
                            help="资源类型 (book|author|series)")
        parser.add_argument("target", nargs="*", help="要删除的ID/关键词/名称")
        parser.add_argument("--all", action="store_true",
                            help="[book/author] 删除所有作品和作者（可与过滤器组合）")
        parser.add_argument("--by-name", action="store_true",
                            help="[book] target 按标题关键词匹配")
        parser.add_argument("-y", "--yes", action="store_true", help="跳过确认")
        parser.add_argument("--keep-file", action="store_true",
                            help="[book] 只从清单移除，保留文件")
        parser.add_argument("--force", action="store_true",
                            help="[series] 强制删除（取消关联所有作品）")
        parser.add_argument("-a", "--author", type=str, default="",
                            help="[book/author/series] 按作者名过滤")
        parser.add_argument("-s", "--series", type=str, default="",
                            help="[book] 按系列名过滤")
        parser.add_argument("-t", "--type", type=str, default="",
                            dest="book_type",
                            help="[book] 按分类过滤（小说|漫画|音乐|电影|美图集）")
        parser.add_argument("--tag", type=str, default="",
                            help="[book] 按标签过滤（子串匹配）")
        parser.add_argument("--favorite", action="store_true", default=False,
                            help="[book] 仅收藏项")
        parser.add_argument("--no-favorite", action="store_true", default=False,
                            help="[book] 仅非收藏项")
        parser.add_argument("--keep-tables", action="store_true", default=False,
                            help="[book --all] 保留作者/系列/计数器表")

    def _has_filters(self, args: argparse.Namespace) -> bool:
        return bool(args.author or args.series or args.book_type
                    or args.tag or args.favorite or args.no_favorite)

    def _confirm_and_delete(self, rows: list[dict], args: argparse.Namespace,
                             prompt: str = "确认删除以上记录？",
                             clear_tables: bool = False) -> int:
        if not rows:
            return self._respond(True, {"deleted": 0})
        if not self._json_mode and not (args.yes or self._no_confirm):
            self._print_info(f"找到 {len(rows)} 条记录:")
            for row in rows[:20]:
                self._print_info(f"  [dim]{row.get('ID')}[/dim] {row.get('标题', '')}")
            if len(rows) > 20:
                self._print_info(f"  ... 还有 {len(rows) - 20} 条")
            if not self._confirm(prompt):
                return 0
        ids = {row.get("ID") for row in rows}
        result = delete_book(ids, keep_file=args.keep_file,
                             clear_tables=clear_tables)
        if self._json_mode:
            return self._respond(True, data=result)
        self._print_info(f"已删除 {result['deleted']} 条记录")
        return 0

    def execute(self, args: argparse.Namespace) -> int:
        if args.author and args.author.startswith("--"):
            return self._respond(False, error="-a/--author 选项缺少参数。提示: delete author --all")
        if args.series and args.series.startswith("--"):
            return self._respond(False, error="-s/--series 选项缺少参数")
        if args.book_type and args.book_type.startswith("--"):
            return self._respond(False, error="-t/--type 选项缺少参数")
        if args.tag and args.tag.startswith("--"):
            return self._respond(False, error="--tag 选项缺少参数")

        tt = args.target_type
        if tt not in ("book", "b", "author", "a", "series", "s"):
            args.target.insert(0, tt)
            tt = "book"

        if tt in ("book", "b"):
            return self._delete_book(args)
        elif tt in ("author", "a"):
            if args.all:
                return self._delete_author(args)
            if not args.target and not args.author:
                return self._respond(False, error="请指定作者标识，或使用 -a 指定作者名")
            return self._delete_author(args)
        elif tt in ("series", "s"):
            if not args.target:
                return self._respond(False, error="请指定系列名")
            return self._delete_series(args)
        else:
            return self._respond(False, error=f"未知资源类型: {tt}，请指定 book/author/series")

    def _delete_book(self, args: argparse.Namespace) -> int:
        rows = filter_rows(
            author=args.author,
            series=args.series,
            book_type=args.book_type,
            tag=args.tag,
            favorite=args.favorite,
            no_favorite=args.no_favorite,
        )

        has_filters = self._has_filters(args)
        clear_tables = args.all and not has_filters and not args.keep_tables

        if args.all or (not args.target and has_filters):
            return self._confirm_and_delete(rows, args, "确认删除以上所有记录？",
                                            clear_tables=clear_tables)

        if not args.target:
            return self._respond(False, error="请提供要删除的ID，"
                                 "或使用 delete --all / 过滤参数（-a/-s/-t/--tag/--favorite）")

        result = delete_by_ids(args.target, by_name=args.by_name,
                               keep_file=args.keep_file)

        if self._json_mode:
            return self._respond(True, data=result)

        self._print_info(f"已删除 {result['deleted']} 条记录")
        return 0

    def _delete_author(self, args: argparse.Namespace) -> int:
        from src.operations import list_items
        authors = list_items("author")["items"]

        if args.target:
            matched = resolve_author_targets(args.target)
        elif args.author:
            matched = [a for a in authors if args.author in a.get("name", "")]
        else:
            matched = authors

        if not matched:
            return self._respond(False, error="未找到匹配的作者")

        if not self._json_mode and not (args.yes or self._no_confirm):
            self._print_info(f"找到 {len(matched)} 位作者:")
            for a in matched[:20]:
                self._print_info(f"  {a['id']}  {a['name']}")
            if len(matched) > 20:
                self._print_info(f"  ... 还有 {len(matched) - 20} 位")
            if not self._confirm("确认删除以上作者及其全部作品？"):
                return 0

        ids = [a["id"] for a in matched]
        deleted, _ = delete_authors(ids)
        if self._json_mode:
            return self._respond(True, data={"deleted": deleted, "ids": ids})
        self._print_info(f"已删除 {deleted} 位作者")
        return 0

    def _delete_series(self, args: argparse.Namespace) -> int:
        deleted, unlinked = delete_series(
            args.target, author=args.author, force=args.force)
        if deleted == 0:
            return self._respond(False, error="未找到匹配的系列")
        msg = f"已删除 {deleted} 个系列"
        if unlinked:
            msg += f"，{unlinked} 个作品被取消关联"
        if self._json_mode:
            return self._respond(True, data={"deleted": deleted, "unlinked_works": unlinked})
        self._print_info(msg)
        return 0
