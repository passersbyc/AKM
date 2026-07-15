import shutil
from pathlib import Path


def format_as_folder(content_dir: Path, dest_dir: Path, safe_name: str) -> Path:
    final = dest_dir / safe_name
    if final.exists():
        shutil.rmtree(final)
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
