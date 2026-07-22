from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import threading


@dataclass
class DownloadContext:
    work_url: str
    temp_file: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    entry: Dict[str, Any] = field(default_factory=dict)
    final_path: Optional[Path] = None
    error: str = ""


class PipelineResult:
    __slots__ = ("status", "reason", "work_url", "final_path")

    def __init__(self, status: str, reason: str, work_url: str,
                 final_path: Optional[Path] = None):
        self.status = status
        self.reason = reason
        self.work_url = work_url
        self.final_path = final_path

    @classmethod
    def success(cls, work_url: str, reason: str = "ok",
                final_path: Optional[Path] = None) -> "PipelineResult":
        return cls("success", reason, work_url, final_path=final_path)

    @classmethod
    def skipped(cls, work_url: str, reason: str = "已存在") -> "PipelineResult":
        return cls("skipped", reason, work_url)

    @classmethod
    def failed(cls, work_url: str, reason: str) -> "PipelineResult":
        return cls("failed", reason, work_url)

    @property
    def ok(self) -> bool:
        return self.status == "success"


class DownloadControl:
    def __init__(self):
        self.pause = threading.Event()
        self.cancel = threading.Event()
        self.sigint_count = 0
        self._stop_events: list = []

    @property
    def paused(self) -> bool:
        return self.pause.is_set()

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def register_stop_event(self, event) -> None:
        """注册下游 stop_event，取消时自动级联 set，实现单一取消源。"""
        if event not in self._stop_events:
            self._stop_events.append(event)

    def request_cancel(self) -> None:
        """统一取消入口：set cancel 并级联到所有已注册的 stop_event。"""
        self.cancel.set()
        for ev in self._stop_events:
            ev.set()
