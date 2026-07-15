import argparse

from src.cli.base import BaseCommand
from src.core.database import short_id
from src.operations import search_works


class SearchCommand(BaseCommand):
    verb = "search"
    nouns = ["author", "label"]
    description = "搜索作品、作者或标签"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("rest", type=str, nargs="*", help="搜索关键词 [数量]")
        parser.add_argument("--author", type=str, default="", help="按作者筛选")
        parser.add_argument("--type", type=str, default="", help="按分类筛选")
        parser.add_argument("--tag", type=str, default="", help="按标签筛选")
        parser.add_argument("--favorite", choices=["yes", "no"], help="按收藏状态筛选")
        parser.add_argument("--regex", action="store_true", help="使用正则表达式匹配")

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        if noun == "author":
            parser.add_argument("query", type=str, help="作者名称关键词")
            parser.add_argument("number", type=int, nargs="?", default=0, help="限制输出数量")
        elif noun == "label":
            parser.add_argument("query", type=str, help="标签关键词")
            parser.add_argument("number", type=int, nargs="?", default=0, help="限制输出数量")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "author":
            return self._search_author(args)
        if noun == "label":
            return self._search_label(args)
        # 解析 rest: [query] [number]
        rest = getattr(args, "rest", []) or []
        query = ""
        number = 0
        if rest:
            query = rest[0]
        if len(rest) >= 2:
            try:
                number = int(rest[1])
            except ValueError:
                pass
        return self._search_work(args, query, number)

    def _search_work(self, args: argparse.Namespace, query: str, number: int) -> int:
        if not query:
            return self.output.result(False, error="请输入搜索关键词")
        items = search_works(
            query=query or "",
            author=args.author or "",
            file_type=args.type or "",
            tags=args.tag or "",
            favorited=args.favorite or "",
            regex=args.regex,
            limit=number,
        )
        total = len(items)

        if self.output.json_mode:
            return self.output.result(True, {"total": total, "items": items})

        if not items:
            self.output.info("[yellow]什么都没有找到[/yellow]")
            return 0

        self.output.info(f"[cyan]找到 {total} 个结果：[/cyan]")
        columns = [
            {"header": "ID", "width": 10},
            {"header": "标题", "style": "green"},
            {"header": "作者", "style": "blue"},
            {"header": "分类", "style": "yellow"},
            {"header": "收藏", "style": "red"},
            {"header": "评分", "style": "cyan"},
        ]
        rows = []
        for row in items:
            rating = row.get("评分", "-") or "0"
            rows.append([
                short_id(str(row.get("ID", "N/A"))),
                row.get("标题", ""),
                row.get("作者", "未知"),
                row.get("分类", "") or "未知",
                "♥" if row.get("收藏", "否") == "是" else "",
                rating if float(rating) > 0 else "",
            ])
        self.output.table("搜索结果", columns, rows)
        return 0

    def _search_label(self, args: argparse.Namespace) -> int:
        from src.core.database import get_db
        db = get_db()
        rows = db.execute(
            "SELECT id, title, tags, file_type, favorite, rating, "
            "(SELECT a.name FROM authors a WHERE a.id = works.author_id) as author_name "
            "FROM works WHERE tags LIKE ? "
            "ORDER BY favorite DESC, rating DESC LIMIT 50",
            (f"%{args.query}%",),
        ).fetchall()
        if args.number > 0:
            rows = rows[:args.number]
        total = len(rows)

        if self.output.json_mode:
            return self.output.result(True, {"total": total, "items": [dict(r) for r in rows]})

        if not rows:
            self.output.info(f"[yellow]没有找到标签 [{args.query}] 的作品[/yellow]")
            return 0

        self.output.info(f"[cyan]标签 [{args.query}] 找到 {total} 个作品：[/cyan]")
        self.output.table("标签搜索结果", [
            {"header": "ID", "width": 10},
            {"header": "标题", "style": "green"},
            {"header": "作者", "style": "blue"},
            {"header": "分类", "style": "yellow"},
            {"header": "标签", "style": "dim", "max_width": 30},
            {"header": "收藏", "style": "red", "width": 4},
        ], [
            [
                short_id(r["id"]),
                r["title"],
                r["author_name"] or "未知",
                r["file_type"] or "未知",
                r["tags"] or "",
                "♥" if r["favorite"] else "",
            ]
            for r in rows
        ])
        return 0

    def _search_author(self, args: argparse.Namespace) -> int:
        from src.core.database import get_db
        db = get_db()
        rows = db.execute(
            "SELECT a.id, a.name, a.favorite, a.source, "
            "COUNT(w.id) as work_count "
            "FROM authors a LEFT JOIN works w ON a.id = w.author_id "
            "WHERE a.name LIKE ? "
            "GROUP BY a.id ORDER BY a.favorite DESC, a.name",
            (f"%{args.query}%",),
        ).fetchall()
        if args.number > 0:
            rows = rows[:args.number]
        total = len(rows)

        if self.output.json_mode:
            return self.output.result(True, {"total": total, "authors": [dict(r) for r in rows]})

        if not rows:
            self.output.info("[yellow]没有找到匹配的作者[/yellow]")
            return 0

        self.output.info(f"[cyan]找到 {total} 位作者：[/cyan]")
        self.output.table("作者搜索结果", [
            {"header": "ID", "style": "magenta", "width": 6},
            {"header": "名称", "style": "bold"},
            {"header": "收藏", "style": "red", "width": 4},
            {"header": "作品数", "justify": "right", "style": "green"},
        ], [
            [r["id"], r["name"], "♥" if r["favorite"] else "", str(r["work_count"])]
            for r in rows
        ])
        return 0
