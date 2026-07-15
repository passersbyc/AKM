"""格式转换统一入口。

各子模块：
    - docx_converter: DOCX/DOC → TXT
    - epub_builder:   EPUB 构建与后处理
    - cjk_converter:  繁简中文转换
    - pdf_converter:  各格式 → PDF
    - image_converter: 图片文件夹 → PDF/CBZ

本文件仅做 re-export，保证向后兼容。
"""

# -- DOCX / DOC → TXT --------------------------------------------------
from src.core.docx_converter import (  # noqa: F401
    convert_to_txt,
    convert_docx_to_txt,
    convert_doc_to_txt,
)

# -- EPUB 构建与后处理 --------------------------------------------------
from src.core.epub_builder import (  # noqa: F401
    convert_to_epub,
)

# -- 繁简中文转换 -------------------------------------------------------
from src.core.cjk_converter import (  # noqa: F401
    is_traditional_chinese,
    convert_to_simplified,
    convert_file_to_simplified,
)

# -- 各格式 → PDF -------------------------------------------------------
from src.core.pdf_converter import (  # noqa: F401
    convert_to_pdf,
)

# -- 图片文件夹 → PDF / CBZ ---------------------------------------------
from src.core.image_converter import (  # noqa: F401
    convert_images_to_book,
)
