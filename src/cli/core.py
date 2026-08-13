"""CLIApp — verb→noun 两级 subparser 框架 + 交互模式（无转译层）。"""
import argparse
import json
import shlex
import sys
import unicodedata
from typing import Optional

from src.cli.base import BaseCommand
from src.core.config import translate_error
from src.core.logging import logger


def _display_width(text: str) -> int:
    """按终端显示列宽计算长度（CJK 宽字符 = 2，组合音标 = 0）。"""
    width = 0
    for ch in text:
        if unicodedata.category(ch) in ("Mn", "Me"):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _truncate_display(text: str, width: int) -> str:
    """按显示宽度截断，超出部分替换为 …（预留 1 列）。"""
    out: list[str] = []
    used = 0
    for ch in text:
        ch_w = _display_width(ch)
        if ch_w == 0:
            out.append(ch)
            continue
        if used + ch_w > width - 1:
            break
        out.append(ch)
        used += ch_w
    result = "".join(out)
    return result + ("…" if len(result) < len(text) else "")


def _wrap_by_width(text: str, width: int) -> list[str]:
    """按显示宽度折行（CJK 感知，优先在空格处断开），返回行列表。"""
    if width <= 8:
        width = 8
    lines: list[str] = []
    cur: list[str] = []
    cur_w = 0
    last_space = -1  # cur 中最后一个空格的下标
    for ch in text:
        ch_w = _display_width(ch)
        if ch_w == 0:
            cur.append(ch)
            continue
        if cur_w + ch_w > width and cur:
            if last_space > 0:
                lines.append("".join(cur[: last_space + 1]).rstrip())
                rest = cur[last_space + 1 :]
                cur = rest[:]
                cur_w = sum(_display_width(c) for c in cur)
            else:
                lines.append("".join(cur))
                cur, cur_w = [], 0
            last_space = -1
        if ch == " ":
            last_space = len(cur)
        cur.append(ch)
        cur_w += ch_w
    if cur:
        lines.append("".join(cur))
    return lines or [""]


class ArgumentParserError(Exception):
    pass


class NoExitArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentParserError(message)

    def exit(self, status=0, message=None):
        if message:
            logger.warning(message)
        raise ArgumentParserError(f"Exited with status {status}")


class CLIApp:
    #: 顶层/交互帮助的命令分组展示顺序；未声明的组按发现顺序排在最后
    GROUP_ORDER: list[str] = [
        "浏览",
        "管理",
        "订阅下载",
        "导出",
        "系统",
    ]

    def __init__(self, prog_name: str = "akm", description: str = "作品管理系统 CLI"):
        self.prog_name = prog_name
        self.description = description
        self.parser = NoExitArgumentParser(prog=prog_name, description=description)
        self.parser.add_argument("--json", action="store_true", help="以JSON格式输出（智能体模式）")
        self.parser.add_argument("--no-confirm", action="store_true", help="跳过所有确认提示（智能体模式）")
        self._verbs = self.parser.add_subparsers(title="命令", dest="verb", required=True)

        self._commands: dict[str, BaseCommand] = {}
        self._verb_parsers: dict[str, argparse.ArgumentParser] = {}
        self._exec_parsers: dict[str, argparse.ArgumentParser] = {}
        self._noun_parsers: dict[tuple[str, str], argparse.ArgumentParser] = {}
        self._noun_subs: dict[str, argparse._SubParsersAction] = {}
        self._welcome_shown = False

    @staticmethod
    def _add_global_flags(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--json", action="store_true", help="以JSON格式输出（智能体模式）")
        parser.add_argument("--no-confirm", action="store_true", help="跳过所有确认提示（智能体模式）")

    def register_command(self, command_cls: type[BaseCommand]) -> None:
        verb = command_cls.verb
        if not verb:
            raise ValueError(f"Command {command_cls.__name__} 缺少 verb 属性")
        if verb in self._commands:
            raise ValueError(f"verb '{verb}' 已注册")
        command = command_cls()
        self._commands[verb] = command

        # 主 parser（用于 --help 显示，含 noun subparsers）
        verb_parser = self._verbs.add_parser(
            verb, help=command_cls.description, description=command_cls.description,
        )
        self._add_global_flags(verb_parser)
        command.configure_parser(verb_parser)
        self._verb_parsers[verb] = verb_parser

        # 独立 parser（用于实际执行，不含 subparsers）
        exec_parser = NoExitArgumentParser(prog=verb, description=command_cls.description)
        self._add_global_flags(exec_parser)
        command.configure_parser(exec_parser)
        self._exec_parsers[verb] = exec_parser

        nouns = command_cls.nouns or []
        if nouns:
            noun_subs = verb_parser.add_subparsers(dest="noun", help="资源类型")
            self._noun_subs[verb] = noun_subs
            for noun in nouns:
                noun_help = command_cls.noun_descriptions.get(noun) or f"{verb} {noun}"
                np = noun_subs.add_parser(noun, help=noun_help)
                self._add_global_flags(np)
                command.configure_noun_parser(np, noun)

                # 独立 noun parser
                exec_np = NoExitArgumentParser(prog=f"{verb} {noun}", description=noun_help)
                self._add_global_flags(exec_np)
                command.configure_noun_parser(exec_np, noun)
                self._noun_parsers[(verb, noun)] = exec_np

    # ── 帮助渲染 ──────────────────────────────────────────

    def _ordered_command_groups(self) -> list[tuple[str, list[tuple[str, type[BaseCommand]]]]]:
        """按 GROUP_ORDER 聚合已注册命令，返回 [(组名, [(verb, 命令类), ...]), ...]。"""
        groups: dict[str, list[tuple[str, type[BaseCommand]]]] = {}
        for verb, command in self._commands.items():
            group = getattr(command, "group", "") or "其他"
            groups.setdefault(group, []).append((verb, type(command)))

        def _group_rank(item: tuple[str, list]) -> tuple[int, int]:
            group = item[0]
            try:
                return (0, self.GROUP_ORDER.index(group))
            except ValueError:
                return (1, list(groups).index(group))

        return sorted(groups.items(), key=_group_rank)

    @staticmethod
    def _noun_hint(nouns: list[str], max_width: int = 26) -> str:
        """生成 [a|b|c] 提示；超宽时在 | 边界截断为 [a|b|…]。"""
        if not nouns:
            return ""
        hint = "[" + "|".join(nouns) + "]"
        if _display_width(hint) <= max_width:
            return hint
        best = ""
        for noun in nouns:
            candidate = f"{best}|{noun}" if best else noun
            if _display_width(f"[{candidate}|…]") > max_width:
                break
            best = candidate
        return f"[{best}|…]" if best else f"[{_truncate_display(nouns[0], max_width - 5)}…]"

    @staticmethod
    def _layout_rows(left_text: str, desc: str, hint: str, width: int, verb_col: int) -> list[tuple[str, str, str]]:
        """排版一条命令为多行：[(左列, 描述, 提示), ...]，续行左列为空格填充，描述按显示宽折行。"""
        first_avail = width - 2 - (verb_col - 2) - 2 - (_display_width(hint) + 2 if hint else 0)
        chunks = _wrap_by_width(desc, max(first_avail, 12))
        rows = [(left_text.ljust(verb_col - 2), chunks[0], hint)]
        rows += [(" " * (verb_col - 2), chunk, "") for chunk in chunks[1:]]
        return rows

    def _print_top_help(self, json_mode: bool = False) -> int:
        """渲染顶层 `akm --help`：rich 分组面板，--json 时输出机器可读清单。"""
        ordered = self._ordered_command_groups()

        if json_mode:
            payload = {
                "program": self.prog_name,
                "description": self.description,
                "usage": f"{self.prog_name} <命令> [参数]  [--json] [--no-confirm]",
                "global_flags": [
                    {"flag": "--json", "help": "以JSON格式输出（智能体模式）"},
                    {"flag": "--no-confirm", "help": "跳过所有确认提示（智能体模式）"},
                ],
                "groups": [
                    {
                        "group": group,
                        "commands": [
                            {
                                "verb": verb,
                                "description": cls.description,
                                "nouns": list(cls.nouns or []),
                                "noun_descriptions": dict(cls.noun_descriptions or {}),
                            }
                            for verb, cls in cmds
                        ],
                    }
                    for group, cmds in ordered
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
        console = Console()
        # Panel 边框 2 + 左右 padding 4*2，内容可用宽
        width = max(60, (console.width or 80) - 10)

        content = Text()
        content.append(f"用法: {self.prog_name} <命令> [参数]  [--json] [--no-confirm]", style="bold")
        content.append(f"\n{self.description}", style="dim")

        for group, cmds in ordered:
            content.append(f"\n\n{group}", style="bold bright_cyan")
            for verb, cls in cmds:
                hint = self._noun_hint(list(cls.nouns or []), 30)
                for left, desc, hint_part in self._layout_rows(verb, cls.description, hint, width, 12):
                    content.append("\n  ")
                    content.append(left, style="bold cyan")
                    content.append(" ")
                    content.append(desc, style="default")
                    if hint_part:
                        content.append("  ")
                        content.append(hint_part, style="italic yellow")
        console.print(Panel(
            content,
            title="[bold]AKM · 作品管理系统[/bold]",
            subtitle="[dim]akm <命令> --help 查看参数  |  直接运行 akm 进入交互模式[/dim]",
            box=box.ROUNDED,
            border_style="bright_cyan",
            padding=(1, 2),
        ))
        return 0

    def _show_welcome_once(self) -> None:
        if self._welcome_shown:
            return
        self._welcome_shown = True
        if "--json" in sys.argv or "--help" in sys.argv or "-h" in sys.argv:
            return
        from src.cli.ui.banner import show_welcome
        show_welcome(self.prog_name)

    def run(self, argv: Optional[list[str]] = None) -> int:
        if argv is None:
            argv = sys.argv[1:]

        if not argv:
            return self.run_interactive()

        # 顶层帮助：无 verb 的 -h/--help（如 `akm --help`、`akm --json -h`）
        # 有 verb 时（`akm list -h`）走 argparse 默认的子命令帮助
        if any(a in ("-h", "--help") for a in argv):
            first_pos = next((a for a in argv if not a.startswith("-")), None)
            if first_pos not in self._commands:
                return self._print_top_help(json_mode="--json" in argv)

        self._show_welcome_once()

        try:
            verb = argv[0]
            # 全局 flag 跳过
            if verb.startswith("-"):
                args = self.parser.parse_args(argv)
                verb = args.verb
                command = self._commands[verb]
                command.set_flags(args.json, args.no_confirm)
                noun = getattr(args, "noun", None)
                # 未指定 noun 时保持 None（走命令默认路径），
                # 不能默认成 nouns[0]：`akm --json list` 会被误分发成列作者
                return command.execute(args, noun=noun)

            command = self._commands.get(verb)
            if command is None:
                logger.error(f"未知命令: {verb}")
                return 1

            # 如果 verb 有 nouns 且第一个非 flag 参数匹配某 noun，用 noun subparser
            remaining = argv[1:]
            command.set_flags("--json" in argv, "--no-confirm" in argv)

            # 找第一个非 flag 参数
            first_pos = None
            first_pos_idx = -1
            for i, a in enumerate(remaining):
                if not a.startswith("-"):
                    first_pos = a
                    first_pos_idx = i
                    break

            if command.nouns and first_pos in command.nouns:
                # 用 noun exec parser
                noun = first_pos
                noun_parser = self._noun_parsers.get((verb, noun))
                if noun_parser is None:
                    logger.error(f"noun {noun} 未注册")
                    return 1
                noun_args = remaining[:first_pos_idx] + remaining[first_pos_idx + 1:]
                args = noun_parser.parse_args(noun_args)
                args.verb = verb
                args.noun = noun
                command.set_flags(getattr(args, "json", False), getattr(args, "no_confirm", False))
                return command.execute(args, noun=noun)
            else:
                # 用 verb exec parser（无 subparsers，不会拦截 positional）
                verb_parser = self._exec_parsers.get(verb)
                if verb_parser is None:
                    logger.error(f"verb {verb} 未注册")
                    return 1
                args = verb_parser.parse_args(remaining)
                args.verb = verb
                args.noun = None
                command.set_flags(getattr(args, "json", False), getattr(args, "no_confirm", False))
                return command.execute(args, noun=None)
        except ArgumentParserError as e:
            if "Exited with status 0" in str(e):
                return 0
            logger.error(f"用法错误: {translate_error(str(e))}")
            return 1
        except Exception as e:
            logger.error(f"错误: {e}")
            return 1

    def _print_interactive_help(self) -> None:
        """交互模式 help — 从已注册命令动态生成（按 group 分组，不再硬编码）。"""
        ordered = self._ordered_command_groups()
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text
            from rich import box
            console = Console()
            width = max(60, (console.width or 80) - 10)

            content = Text()
            for group_i, (group, cmds) in enumerate(ordered):
                if group_i:
                    content.append("\n\n")
                content.append(group, style="bold bright_cyan")
                for verb, cls in cmds:
                    nouns = list(cls.nouns or [])
                    usage = f"{verb} {self._noun_hint(nouns, 20)}".rstrip()
                    for left, desc, _hint in self._layout_rows(usage, cls.description, "", width, 32):
                        content.append("\n  ")
                        content.append(left, style="bold white")
                        content.append(" ")
                        content.append(desc, style="dim")
            console.print(Panel(
                content,
                title="[bold]可用的命令们[/bold]",
                subtitle="[dim]输入 <命令> --help 查看参数  |  exit 退出哦[/dim]",
                box=box.ROUNDED,
                border_style="bright_cyan",
                padding=(1, 2),
            ))
        except ImportError:
            print("\n可用的命令们:")
            for group, cmds in ordered:
                print(f"\n  {group}")
                for verb, cls in cmds:
                    nouns = list(cls.nouns or [])
                    usage = f"{verb} {self._noun_hint(nouns, 20)}".rstrip()
                    print(f"    {usage:<28}  {cls.description}")
            print("\n输入 <命令> --help 查看参数  |  exit 退出哦\n")

    def run_interactive(self) -> int:
        from src.cli.ui.banner import show_interactive_banner
        show_interactive_banner(
            self.prog_name,
            [(verb, cls.description) for verb, cls in self._commands.items()],
        )
        self._welcome_shown = True

        from src.cli.completion import build_completer
        session = build_completer(self)
        use_ptk = session is not None

        while True:
            try:
                if use_ptk:
                    user_input = session.prompt(f"{self.prog_name}> ")
                else:
                    user_input = input(f"{self.prog_name}> ")
                user_input = user_input.strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    break
                if user_input.lower() in ("help", "?"):
                    self._print_interactive_help()
                    continue

                is_windows = sys.platform.startswith("win")
                try:
                    argv = shlex.split(user_input, posix=not is_windows)
                except ValueError as e:
                    print(f" 解析错误: {translate_error(str(e))}")
                    continue
                if is_windows:
                    argv = [arg.strip("\"'") for arg in argv]

                try:
                    self.run(argv)
                except ArgumentParserError as e:
                    print(f" 错误: {e}")
                except SystemExit:
                    pass
            except KeyboardInterrupt:
                print("\n输入 'exit' 退出程序哦。")
            except EOFError:
                print("\n 正在退出...")
                break
            except Exception as e:
                print(f" 意外错误: {e}")

        return 0
