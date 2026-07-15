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

    @property
    def paused(self) -> bool:
        return self.pause.is_set()

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()
