from pathlib import Path
import zipfile


def check_file_integrity(file_path: Path) -> bool:
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    suffix = file_path.suffix.lower()
    try:
        if suffix in ['.zip', '.cbz', '.epub']:
            if not zipfile.is_zipfile(file_path):
                return False
            with zipfile.ZipFile(file_path, 'r') as zf:
                if zf.testzip() is not None:
                    return False
            return True
        elif suffix == '.pdf':
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                if len(reader.pages) == 0:
                    return False
                _ = reader.metadata
                return True
            except Exception:
                with open(file_path, 'rb') as f:
                    header = f.read(5)
                    if header != b'%PDF-':
                        return False
                return True
        elif suffix in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']:
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    img.verify()
                return True
            except Exception:
                return False
    except Exception:
        return False
    return True
