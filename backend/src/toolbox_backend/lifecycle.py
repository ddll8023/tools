"""编排应用启动期的目录初始化、凭据生成、临时清理和本地能力探测，并在关闭时结束局域网投送会话。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from toolbox_backend.core.capabilities import (
    CAPABILITY_ID_PHOTO,
    CAPABILITY_LIBREOFFICE,
    capabilities,
)
from toolbox_backend.core.config import settings
from toolbox_backend.core.control_auth import initialize_control_token
from toolbox_backend.integrations.libreoffice import check_available
from toolbox_backend.modules.id_photo.model_management import get_model_status
from toolbox_backend.modules.lan_transfer.service import recover_on_startup, shutdown_session
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.infrastructure.task_storage.cleanup import cleanup_expired_temp

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """初始化本地运行目录和工具能力状态。"""
    os.makedirs(settings.data_root, exist_ok=True)

    logger.info("初始化控制面凭据...")
    initialize_control_token()

    logger.info("启动清理过期临时文件...")
    cleanup_expired_temp()

    # 上次异常终止可能留下未确认的投送内容，这里专门回收，不触碰接收目录。
    logger.info("回收上次遗留的投送内容...")
    recover_on_startup()

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

    # 桌面外壳以 SIGTERM 停止后端时依赖此处完成会话关闭；强制终止的
    # 情形不执行回调，阶段一没有落盘的会话状态需要回收。
    logger.info("关闭局域网投送会话...")
    shutdown_session()
