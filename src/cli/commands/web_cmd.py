"""startui 命令 — 启动 FastAPI Web UI 服务器并自动打开浏览器。"""
import argparse
import socket
import threading
import urllib.request
import webbrowser

from src.cli.base import BaseCommand


def _find_free_port(host: str, preferred: int, max_tries: int = 10) -> int:
    """从 preferred 开始找可用端口，最多尝试 max_tries 次。"""
    for offset in range(max_tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return -1


def _is_akm_running(host: str, port: int, timeout: float = 0.6) -> bool:
    """探测 host:port 是否跑着 AKM WebUI（请求 /health）。"""
    try:
        url = f"http://{host}:{port}/health"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _find_existing(host: str, preferred: int, max_tries: int = 10) -> int:
    """从 preferred 开始找已运行的 AKM 实例端口；无则返回 -1。"""
    for offset in range(max_tries):
        port = preferred + offset
        if _is_akm_running(host, port):
            return port
    return -1


class StartUICommand(BaseCommand):
    verb = "startui"
    nouns: list[str] = []
    description = "启动 Web UI 界面（自动打开浏览器）"
    group = "系统"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）～")
        parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000，被占用时自动递增）～")
        parser.add_argument("--reload", action="store_true", help="热重载（开发模式）～")
        parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器～")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        import uvicorn
        from src.web import create_app

        # 单实例：已有 AKM 在跑则直接打开复用，不重复启动
        existing = _find_existing(args.host, args.port)
        if existing != -1:
            url = f"http://{args.host}:{existing}"
            self.output.info(f"WebUI 已在运行: {url}，直接打开～")
            if not args.no_browser:
                webbrowser.open(url)
            return 0

        port = _find_free_port(args.host, args.port)
        if port == -1:
            self.output.error(f"端口 {args.port}~{args.port + 9} 均被占用，请手动指定: --port <port>")
            return 1
        if port != args.port:
            self.output.warn(f"端口 {args.port} 被占用，自动切换到 {port} 啦～")

        app = create_app()
        url = f"http://{args.host}:{port}"
        self.output.info(f"AKM WebUI 启动中... {url}")

        # 延迟 1.5s 打开浏览器，等 uvicorn 起来
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()

        # reload 模式要求 import 字符串 + factory=True（传 app 对象会直接退出）
        if args.reload:
            uvicorn.run(
                "src.web.app:create_app",
                host=args.host, port=port,
                reload=True, factory=True,
            )
        else:
            uvicorn.run(app, host=args.host, port=port)
        return 0
