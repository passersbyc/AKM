from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal


@dataclass
class ExportRequest:
    query: str
    dest_dir: Path
    export_name: str
    mode: Literal["author", "tag", "id", "work", "mylikeauthor", "mylikeworks"] = "author"
    filter_type: Optional[str] = None
    limit: int = 0
    output_format: Literal["folder", "zip", "epub", "completeness"] = "folder"
    author_ids: list[str] = field(default_factory=list)
    favorited_only: bool = False
    # 行已由调用方筛选完成（如 web 按当前筛选导出），跳过 collect 阶段的二次过滤
    prefiltered: bool = False


@dataclass
class MergeMeta:
    book_title: str
    book_author: str
    series: str = ""


@dataclass
class TypeGroup:
    file_type: str
    series_groups: dict[str, list[dict]] = field(default_factory=dict)
    standalone: list[dict] = field(default_factory=list)


@dataclass
class ExportPlan:
    standalone: list[dict]
    series_groups: dict[str, list[dict]]
    type_groups: dict[str, TypeGroup]
    is_tag_mode: bool = False


@dataclass
class ExportResult:
    success: bool
    exported_count: int
    destination: Optional[Path] = None
    results: Optional[dict] = None
    error: Optional[str] = None
