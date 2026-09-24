"""聚合 v1 API 路由，并统一管理公开版本前缀。"""

from fastapi import APIRouter

from toolbox_backend.api.v1.health import router as health_router
from toolbox_backend.api.v1.settings import router as settings_router
from toolbox_backend.modules.epub_to_markdown.router import router as epub_to_markdown_router
from toolbox_backend.modules.id_photo.router import router as id_photo_router
from toolbox_backend.modules.image_converter.router import router as image_converter_router
from toolbox_backend.modules.tool_catalog.router import router as tools_list_router
from toolbox_backend.modules.markdown_to_pdf.router import router as markdown_to_pdf_router
from toolbox_backend.modules.markdown_to_word.router import router as markdown_to_word_router
from toolbox_backend.modules.pdf_to_markdown.router import router as pdf_to_markdown_router
from toolbox_backend.modules.pdf_to_word.router import router as pdf_to_word_router
from toolbox_backend.modules.qr_code.router import router as qr_code_router
from toolbox_backend.modules.word_to_pdf.router import router as word_to_pdf_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(tools_list_router)
router.include_router(pdf_to_markdown_router)
router.include_router(word_to_pdf_router)
router.include_router(image_converter_router)
router.include_router(epub_to_markdown_router)
router.include_router(pdf_to_word_router)
router.include_router(markdown_to_word_router)
router.include_router(markdown_to_pdf_router)
router.include_router(qr_code_router)
router.include_router(id_photo_router)
router.include_router(settings_router)
