"""CLIApp — verb→noun 两级 subparser 框架 + 交互模式（无转译层）。"""
import argparse
import json
import shlex
import sys
from typing import Optional

from src.cli.base import BaseCommand
from src.core.config import translate_error
from src.core.logging import logger


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
                np = noun_subs.add_parser(noun, help=f"{noun}")
                self._add_global_flags(np)
                command.configure_noun_parser(np, noun)

                # 独立 noun parser
                exec_np = NoExitArgumentParser(prog=f"{verb} {noun}", description=f"{noun}")
                self._add_global_flags(exec_np)
                command.configure_noun_parser(exec_np, noun)
                self._noun_parsers[(verb, noun)] = exec_np

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
                if command.nouns and not noun:
                    noun = command.nouns[0]
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
        groups = [
            ("浏览", [
                ("list [N]", "列出作品"),
                ("list author [N]", "列出作者"),
                ("open <id/名称>", "打开作品文件"),
                ("open url <id/名称/作者>", "打开来源网址"),
                ("search <关键词> [N]", "搜索作品"),
                ("search author <关键词> [N]", "搜索作者"),
                ("search label <标签> [N]", "按标签搜索"),
                ("stats", "库仪表盘"),
            ]),
            ("增删改", [
                ("import <路径>", "导入文件"),
                ("edit <id/名称>", "交互式编辑作品"),
                ("delete <id/名称>", "删除作品"),
                ("delete author <id/名称>", "删除作者"),
                ("delete all", "清空库"),
            ]),
            ("订阅", [
                ("follow", "同步下载队列"),
                ("follow <url>", "关注作者"),
                ("pull", "下载队列作品"),
            ]),
        ]
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text
            from rich import box
            console = Console()
            content = Text()
            for i, (group_name, cmds) in enumerate(groups):
                if i:
                    content.append("\n")
                content.append(f"  {group_name}\n", style="bold bright_cyan")
                for canonical, desc in cmds:
                    content.append(f"    {canonical:<28}", style="bold white")
                    content.append(f"  {desc}\n", style="dim")
            console.print(Panel(
                content,
                title="[bold]可用命令[/bold]",
                subtitle="[dim]输入 <命令> --help 查看参数  |  exit 退出[/dim]",
                box=box.ROUNDED,
                border_style="bright_cyan",
                padding=(1, 2),
            ))
        except ImportError:
            print(f"\n可用命令:")
            for group_name, cmds in groups:
                print(f"\n  {group_name}")
                for canonical, desc in cmds:
                    print(f"    {canonical:<28}  {desc}")
            print("\n输入 <命令> --help 查看参数  |  exit 退出\n")

    def run_interactive(self) -> int:
        from src.cli.ui.banner import show_interactive_banner
        show_interactive_banner(self.prog_name)
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
                    print(f"解析错误: {translate_error(str(e))}")
                    continue
                if is_windows:
                    argv = [arg.strip("\"'") for arg in argv]

                try:
                    self.run(argv)
                except ArgumentParserError as e:
                    print(f"错误: {e}")
                except SystemExit:
                    pass
            except KeyboardInterrupt:
                print("\n输入 'exit' 退出程序。")
            except EOFError:
                print("\n正在退出...")
                break
            except Exception as e:
                print(f"意外错误: {e}")

        return 0
