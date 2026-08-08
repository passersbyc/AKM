import shutil
from datetime import datetime
from pathlib import Path


def format_as_folder(content_dir: Path, dest_dir: Path, safe_name: str) -> Path:
    final = dest_dir / safe_name
    if final.exists():
        try:
            shutil.rmtree(final)
        except BaseException:
            # 目标目录无法删除（如运行环境文件保护拦截）时，
            # 保留旧导出，新导出追加时间戳后缀，避免导出失败或丢失旧数据
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            final = dest_dir / f"{safe_name}-{stamp}"
    shutil.move(str(content_dir), str(final))
    return final


def format_as_zip(temp_dir: Path, dest_dir: Path, safe_name: str) -> Path:
    final = dest_dir / f"{safe_name}.zip"
    shutil.make_archive(
        base_name=str(dest_dir / safe_name),
        format='zip',
        root_dir=str(temp_dir),
        base_dir=safe_name
    )
    return final
