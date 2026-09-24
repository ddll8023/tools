"""聚合应用对外提供的 API 版本路由。"""

from fastapi import APIRouter

from toolbox_backend.api.v1.router import router as v1_router

router = APIRouter()
router.include_router(v1_router)
