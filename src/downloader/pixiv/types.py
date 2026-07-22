from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


@dataclass
class ExtractMessage:
    type: Literal["url", "metadata", "file", "error"]
    url: str
    data: Optional[dict] = None
    path: Optional[Path] = None
    parent: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def url_msg(cls, url: str, parent: Optional[str] = None) -> "ExtractMessage":
        return cls(type="url", url=url, parent=parent)

    @classmethod
    def metadata_msg(cls, url: str, data: dict) -> "ExtractMessage":
        return cls(type="metadata", url=url, data=data)

    @classmethod
    def file_msg(cls, url: str, path: Path, data: Optional[dict] = None, parent: Optional[str] = None) -> "ExtractMessage":
        return cls(type="file", url=url, path=path, data=data, parent=parent)

    @classmethod
    def error_msg(cls, url: str, error: str, parent: Optional[str] = None) -> "ExtractMessage":
        return cls(type="error", url=url, error=error, parent=parent)


@dataclass
class WorkInfo:
    id: str
    type: str = "illust"
    title: str = ""
    author: str = ""
    series: Optional[str] = None
    series_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    description: str = ""
    like_count: int = 0
    view_count: int = 0
    bookmark_count: int = 0
    comment_count: int = 0
    page_count: int = 1
    illust_type: int = 0
    create_date: str = ""
    user_id: str = ""
    _original_url: str = ""
    _thumbnail_url: str = ""
    _body: Optional[dict] = None

    def to_metadata_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "series": self.series,
            "series_id": self.series_id,
            "tags": self.tags,
            "description": self.description,
            "like_count": self.like_count,
            "view_count": self.view_count,
            "bookmark_count": self.bookmark_count,
            "comment_count": self.comment_count,
            "page_count": self.page_count,
            "illust_type": self.illust_type,
            "create_date": self.create_date,
            "user_id": self.user_id,
            "type": self.type,
            "id": self.id,
            "_original_url": self._original_url,
            "_thumbnail_url": self._thumbnail_url,
        }
