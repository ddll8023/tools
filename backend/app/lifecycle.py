"""编排应用启动期的目录初始化、临时清理和本地能力探测。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.capabilities import (
    CAPABILITY_ID_PHOTO,
    CAPABILITY_LIBREOFFICE,
    capabilities,
)
from app.core.config import settings
from app.integrations.libreoffice import check_available
from app.services.tools.id_photo import get_model_status
from app.utils.logger_config import setup_logger
from app.infrastructure.task_storage.cleanup import cleanup_expired_temp

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """初始化本地运行目录和工具能力状态。"""
    os.makedirs(settings.data_root, exist_ok=True)

    logger.info("启动清理过期临时文件...")
    cleanup_expired_temp()

    logger.info("检测 LibreOffice...")
    capabilities.set(CAPABILITY_LIBREOFFICE, check_available())

    logger.info("检测证件照模型和运行依赖...")
    id_photo_ok, id_photo_reason = get_model_status()
    capabilities.set(CAPABILITY_ID_PHOTO, id_photo_ok, id_photo_reason)
    if id_photo_ok:
        logger.info("证件照模型检测成功")
    else:
        logger.warning("证件照工具不可用: %s", id_photo_reason)
    yield
