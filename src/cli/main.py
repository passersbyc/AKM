import sys

from src.cli.core import CLIApp
from src.core.config import get_library_path
from src.core.logging import setup_logging


def load_commands(app: CLIApp) -> None:
    from src.cli.commands.stats_cmd import StatsCommand
    from src.cli.commands.import_cmd import ImportCommand
    from src.cli.commands.search_cmd import SearchCommand
    from src.cli.commands.list_cmd import ListCommand
    from src.cli.commands.open_cmd import OpenCommand
    from src.cli.commands.edit_cmd import EditCommand
    from src.cli.commands.delete_cmd import DeleteCommand
    from src.cli.commands.follow_cmd import FollowCommand
    from src.cli.commands.pull_cmd import PullCommand
    from src.cli.commands.export import ExportCommand
    from src.cli.commands.setting_cmd import SettingCommand
    from src.cli.commands.web_cmd import StartUICommand

    for cls in (
        StatsCommand,
        ImportCommand,
        SearchCommand,
        ListCommand,
        OpenCommand,
        EditCommand,
        DeleteCommand,
        FollowCommand,
        PullCommand,
        ExportCommand,
        SettingCommand,
        StartUICommand,
    ):
        app.register_command(cls)


def main() -> int:
    setup_logging()
    app = CLIApp(prog_name="akm", description="作品管理系统 CLI")
    load_commands(app)
    library_path = get_library_path()
    library_path.mkdir(parents=True, exist_ok=True)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
