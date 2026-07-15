import argparse
from src.cli.core import BaseCommand
from src.operations import edit, edit_book, edit_author, edit_series, get_book
from src.core.registry import short_id


class EditCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return "编辑作品/作者/系列元数据"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target_type", nargs="?", default="id",
                            help="资源类型 (book|author|series)，或直接给作品 ID")
        parser.add_argument("target", nargs="?", default=None, help="ID/名称（指定了类型时需要）")
        parser.add_argument("-f", "--favorite", type=str, choices=["yes", "no"], help="[book/author] 收藏状态")
        parser.add_argument("-r", "--rating", type=float, help="[book] 评分 (0-10)")
        parser.add_argument("-d", "--description", type=str, help="[book] 简介")
        parser.add_argument("-g", "--tags", type=str, help="[book] 替换全部标签")
        parser.add_argument("--add-tag", type=str, help="[book] 添加标签")
        parser.add_argument("--rm-tag", type=str, help="[book] 删除标签")
        parser.add_argument("-a", "--author", type=str, help="[book] 修改作者 / [series] 所属作者")
        parser.add_argument("-s", "--series", type=str, help="[book] 修改系列")
        parser.add_argument("-l", "--like", type=int, nargs="?", const=1, default=None, help="[book] 增加点赞数")
        parser.add_argument("--name", "-n", type=str, default=None, help="[author/series] 新名称")
        parser.add_argument("--note", "-m", type=str, default=None, help="[author] 备注")

    def execute(self, args: argparse.Namespace) -> int:
        tt = args.target_type
        if tt in ("book", "b", "author", "a", "series", "s"):
            if not args.target:
                msg = "请指定目标: edit {book|author|series} <ID>"
                return self._respond(False, error=msg)
        else:
            args.target = tt
            tt = "book"

        if tt in ("book", "b"):
            return self._edit_book(args)
        elif tt in ("author", "a"):
            return self._edit_author(args)
        elif tt in ("series", "s"):
            return self._edit_series(args)

    def _edit_book(self, args: argparse.Namespace) -> int:
        bid = args.target

        field_updates = {}
        edits_pixiv_fields = any([
            args.tags is not None,
            args.add_tag is not None,
            args.rm_tag is not None,
            args.description is not None,
            args.like is not None,
        ])
        if edits_pixiv_fields:
            book = get_book(bid)
            if not book:
                return self._respond(False, error=f"未找到ID: {bid}")
            if "pixiv.net" in (book.get("来源", "") or ""):
                if not self._json_mode:
                    self._print_info(f"[yellow]⚠ 来源为 Pixiv，建议用 source update {bid} 而非手动编辑[/yellow]")
                    if not self._confirm("确认编辑？此修改可能被 source update 覆盖"):
                        return 0
        else:
            book = None

        if args.favorite == "yes":
            field_updates["收藏"] = "是"
        elif args.favorite == "no":
            field_updates["收藏"] = "否"
        if args.rating is not None:
            if not 0.0 <= args.rating <= 10.0:
                return self._respond(False, error="评分必须在 0-10 之间")
            field_updates["评分"] = str(args.rating) if args.rating > 0 else ""
        if args.description is not None:
            field_updates["简介"] = args.description
        if args.tags is not None:
            field_updates["标签"] = args.tags
        if args.add_tag is not None:
            if not book:
                book = get_book(bid)
                if not book:
                    return self._respond(False, error=f"未找到ID: {bid}")
            existing = set(t.strip() for t in book.get("标签", "").split(",") if t.strip())
            new_tags = set(t.strip() for t in args.add_tag.split(",") if t.strip())
            if new_tags <= existing:
                return self._respond(False, error=f"标签已存在: {', '.join(sorted(new_tags))}")
            field_updates["标签"] = ",".join(sorted(existing | new_tags))
        if args.rm_tag is not None:
            if not book:
                book = get_book(bid)
                if not book:
                    return self._respond(False, error=f"未找到ID: {bid}")
            existing = set(t.strip() for t in book.get("标签", "").split(",") if t.strip())
            remove = set(t.strip() for t in args.rm_tag.split(",") if t.strip())
            if not (remove & existing):
                return self._respond(False, error=f"标签不存在: {', '.join(sorted(remove))}")
            field_updates["标签"] = ",".join(sorted(existing - remove))
        if args.like is not None:
            if not book:
                book = get_book(bid)
                if not book:
                    return self._respond(False, error=f"未找到ID: {bid}")
            if args.like < 0:
                return self._respond(False, error="点赞数必须为正整数")
            field_updates["点赞"] = str(int(book.get("点赞", "0") or "0") + args.like)

        updated = edit_book(
            bid, field_updates,
            new_author=args.author or "",
            new_series=args.series or "",
        )
        if not updated:
            return self._respond(False, error=f"未找到ID: {bid}")

        old_id = short_id(bid)
        new_id = short_id(updated.get("ID", ""))
        if self._json_mode:
            result = {"book": updated}
            if old_id != new_id:
                result["old_id"] = old_id
                result["new_id"] = new_id
            return self._respond(True, data=result)

        if old_id != new_id:
            self._print_info(f"ID 变更: {old_id} → {new_id}")
        changes = []
        if args.favorite:
            changes.append(f"收藏: {updated.get('收藏', '')}")
        if args.rating is not None:
            changes.append(f"评分: {updated.get('评分', '')}")
        if args.description:
            changes.append("简介已更新")
        if args.tags:
            changes.append(f"标签: {updated.get('标签', '')}")
        if args.add_tag:
            changes.append(f"添加标签: {args.add_tag}")
        if args.rm_tag:
            changes.append(f"删除标签: {args.rm_tag}")
        if args.author:
            changes.append(f"作者: {updated.get('作者', '')}")
        if args.series:
            changes.append(f"系列: {updated.get('系列', '')}")
        if args.like is not None:
            changes.append(f"点赞: {updated.get('点赞', '0')}")
        self._print_info(f"{updated.get('标题', '')} 更新成功: {', '.join(changes)}")
        return 0

    def _edit_author(self, args: argparse.Namespace) -> int:
        from src.operations.edit_op import author_resolve

        targets = [t.strip() for t in args.target.split(",") if t.strip()]
        if len(targets) > 1 and self._json_mode:
            results = []
            for t in targets:
                r = edit_author(t, name=args.name, note=args.note, favorite=args.favorite)
                results.append({"target": t, "ok": bool(r and not r.get("error")), "data": r})
            return self._respond(True, data={"results": results})

        updated_names = []
        for t in targets:
            author = author_resolve(t)
            if not author:
                self._print(f"[dim]未找到: {t}[/dim]")
                continue
            r = edit_author(t, name=args.name, note=args.note, favorite=args.favorite)
            if r and not r.get("error"):
                updated_names.append(author["name"])

        if not updated_names:
            return self._respond(False, error=f"未找到作者: {args.target}")

        action_parts = []
        if args.favorite == "yes":
            action_parts.append("加入收藏")
        elif args.favorite == "no":
            action_parts.append("取消收藏")
        if args.name:
            action_parts.append(f"改名为 {args.name}")
        if args.note:
            action_parts.append("更新备注")
        action = "、".join(action_parts) if action_parts else "已更新"

        names = ", ".join(updated_names)
        self._print_info(f"已将 {len(updated_names)} 位作者: {names} {action}")
        return 0

    def _edit_series(self, args: argparse.Namespace) -> int:
        targets = [t.strip() for t in args.target.split(",") if t.strip()]
        updated = []
        for t in targets:
            result = edit_series(t, name=args.name, author=args.author)
            if result and not result.get("error"):
                updated.append(t)
            else:
                self._print(f"[dim]未找到: {t}[/dim]")
        if updated:
            self._print_info(f"已将 {len(updated)} 个系列加入: {', '.join(updated)}")
        return 0
