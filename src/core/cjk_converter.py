"""繁简中文转换模块。"""

import zipfile
from pathlib import Path

from src.core.logging import logger


def is_traditional_chinese(text: str) -> bool:
    try:
        import zhconv
        simplified = zhconv.convert(text, 'zh-hans')
        return simplified != text
    except ImportError:
        return False


def convert_to_simplified(text: str) -> str:
    try:
        import zhconv
        return zhconv.convert(text, 'zh-hans')
    except ImportError:
        return text


def convert_file_to_simplified(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()

    if suffix == '.txt':
        try:
            content = file_path.read_text(encoding='utf-8')
            converted = convert_to_simplified(content)
            if converted != content:
                file_path.write_text(converted, encoding='utf-8')
                return True
            return False
        except Exception:
            logger.debug("txt繁简转换失败", exc_info=True)
            return False

    elif suffix == '.epub':
        try:

            with zipfile.ZipFile(file_path, 'r') as zip_read:
                file_list = zip_read.namelist()
                modified = False
                new_files = {}
                compress_info = {}

                for name in file_list:
                    info = zip_read.getinfo(name)
                    compress_info[name] = info.compress_type
                    data = zip_read.read(name)
                    if name.endswith(('.xhtml', '.html', '.htm', '.xml')):
                        content = data.decode('utf-8')
                        converted = convert_to_simplified(content)
                        if converted != content:
                            new_files[name] = converted.encode('utf-8')
                            modified = True
                        else:
                            new_files[name] = data
                    else:
                        new_files[name] = data

                if modified:
                    with zipfile.ZipFile(file_path, 'w') as zip_write:
                        if 'mimetype' in new_files:
                            zip_write.writestr('mimetype', new_files['mimetype'], compress_type=zipfile.ZIP_STORED)
                        for name in file_list:
                            if name != 'mimetype':
                                ct = compress_info.get(name, zipfile.ZIP_DEFLATED)
                                zip_write.writestr(name, new_files[name], compress_type=ct)
                        return True
                return False
        except Exception:
            logger.debug("epub繁简转换失败", exc_info=True)
            return False

    return False
