"""webui 命令 — 启动/关闭 FastAPI Web UI 服务器。

用法：
    akm webui            # 启动 WebUI（已有实例则直接打开复用）
    akm webui close      # 关闭正在运行的 WebUI
"""
import argparse
import os
import shutil
import signal
import socket
import subprocess
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


def _pids_on_port(port: int) -> list[int]:
    """返回监听指定端口的进程 PID（仅 LISTEN 状态，避免误杀浏览器等连接者）。"""
    if shutil.which("lsof"):
        try:
            out = subprocess.run(
                ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                return [int(p) for p in out.stdout.strip().split() if p.isdigit()]
        except Exception:
            pass
    return []


class WebUICommand(BaseCommand):
    verb = "webui"
    nouns: list[str] = ["close"]
    description = "启动/关闭 Web UI（默认打开浏览器）"
    group = "系统"
    noun_descriptions = {"close": "关闭正在运行的 WebUI"}

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）～")
        parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000，被占用时自动递增）～")
        parser.add_argument("--reload", action="store_true", help="热重载（开发模式）～")
        parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器～")

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        """close 子命令参数（与 verb 级一致）。"""
        if noun == "close":
            parser.add_argument("--host", default="127.0.0.1", help="绑定地址～")
            parser.add_argument("--port", type=int, default=8000, help="端口～")

    def execute(self, args: argparse.Namespace, noun: str | None = None) -> int:
        if noun == "close":
            return self._close(args)
        return self._open(args)

    def _close(self, args: argparse.Namespace) -> int:
        """关闭正在运行的 WebUI。"""
        existing = _find_existing(args.host, args.port)
        if existing == -1:
            self.output.info("(・ω・) WebUI 没有在运行呢～")
            return 0
        pids = _pids_on_port(existing)
        if not pids:
            self.output.warn(f"端口 {existing} 有 WebUI 在跑，但没找到监听进程呢～")
            return 1
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except Exception as e:
                self.output.error(f"关闭 PID {pid} 失败: {e}")
                return 1
        self.output.info(f"已关闭 WebUI（端口 {existing}）～")
        return 0

    def _open(self, args: argparse.Namespace) -> int:
        """启动 WebUI（已有实例则直接打开复用）。"""
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
