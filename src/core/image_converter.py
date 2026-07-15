"""图片文件夹 → PDF / CBZ 转换模块。"""

import re
import shutil
import zipfile
from pathlib import Path

from src.core.logging import logger


def convert_images_to_book(folder_path: Path, target_format: str = 'pdf', delete_original: bool = True) -> Path:
    if not folder_path.exists() or not folder_path.is_dir():
        raise ValueError(f"路径不存在或不是文件夹: {folder_path}")

    target_format = target_format.lower()
    if target_format not in ['pdf', 'cbz']:
        raise ValueError(f"不支持的格式: {target_format}。仅支持 'pdf' 或 'cbz'")

    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

    def natural_sort_key(path):
        return [int(text) if text.isdigit() else text.lower()
                for text in re.split(r'(\d+)', path.name)]

    images = [
        p for p in folder_path.iterdir()
        if p.is_file() and p.suffix.lower() in image_extensions and not p.name.startswith('.')
    ]
    images.sort(key=natural_sort_key)

    if not images:
        raise ValueError(f"在 {folder_path} 中未找到支持的图片文件")

    output_path = folder_path.parent / (folder_path.name + f'.{target_format}')

    try:
        if target_format == 'pdf':
            try:
                from PIL import Image
            except ImportError:
                raise ImportError("生成 PDF 需要安装 Pillow 库。请运行: pip install Pillow")

            opened_images = []
            try:
                first_image = Image.open(images[0])
                opened_images.append(first_image)
                if first_image.mode != 'RGB':
                    first_image = first_image.convert('RGB')
                other_images = []
                for img_path in images[1:]:
                    img = Image.open(img_path)
                    opened_images.append(img)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    other_images.append(img)
                first_image.save(
                    output_path, "PDF", resolution=100.0,
                    save_all=True, append_images=other_images,
                )
            finally:
                for img in opened_images:
                    try:
                        img.close()
                    except Exception:
                        pass
        elif target_format == 'cbz':
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for img_path in images:
                    zf.write(img_path, arcname=img_path.name)

        if delete_original:
            try:
                shutil.rmtree(folder_path)
            except Exception as e:
                logger.warning(f"警告: 删除原文件夹失败: {e}")
        return output_path
    except Exception as e:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"转换失败: {e}")
