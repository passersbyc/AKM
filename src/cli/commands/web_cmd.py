"""web 命令 — 启动 FastAPI Web UI 服务器。"""
import argparse

from src.cli.base import BaseCommand


class WebCommand(BaseCommand):
    verb = "web"
    nouns: list[str] = []
    description = "启动 Web UI 界面（浏览器访问）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
        parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
        parser.add_argument("--reload", action="store_true", help="热重载（开发模式）")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        import uvicorn
        from src.web import create_app

        app = create_app()
        self.output.info(f"AKM WebUI 启动中... http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
        return 0
