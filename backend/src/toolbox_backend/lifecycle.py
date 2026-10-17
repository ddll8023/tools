"""编排应用启动期的所有权、目录初始化、凭据生成、临时清理和本地能力探测，并在关闭时确认 USB 与投送会话停止。"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from toolbox_backend.core import runtime
from toolbox_backend.core.capabilities import (
    CAPABILITY_ID_PHOTO,
    CAPABILITY_LIBREOFFICE,
    CAPABILITY_USB_TRANSFER,
    capabilities,
)
from toolbox_backend.core.config import settings
from toolbox_backend.core.control_auth import initialize_control_token
from toolbox_backend.integrations.libreoffice import check_available
from toolbox_backend.modules.id_photo.model_management import get_model_status
from toolbox_backend.modules.lan_transfer.service import recover_on_startup, shutdown_session
from toolbox_backend.modules.usb_transfer import service as usb_transfer_service
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.infrastructure.task_storage.cleanup import cleanup_expired_temp

logger = setup_logger(__name__)

_shutdown_lock = threading.Lock()
_shutdown_done = threading.Event()
_shutdown_started = False
# 停止是否确认完成；与 _shutdown_done 配合，使等待方得到同一结论。
_shutdown_confirmed = False

def request_shutdown(reason: str) -> bool:
    """幂等地停止 USB 与投送会话，返回是否已确认结束。

    首个调用者执行停止动作并阻塞到确认或超时；并发调用只等待同一结论，
    避免窗口关闭、退出和更新安装重复触发或互相打断。
    强制中断或超时返回 False，不冒充正常停止。
    """
    global _shutdown_started, _shutdown_confirmed
    with _shutdown_lock:
        if _shutdown_done.is_set():
            return _shutdown_confirmed
        owner = not _shutdown_started
        _shutdown_started = True
    if not owner:
        _shutdown_done.wait(settings.APP_SHUTDOWN_TIMEOUT_SECONDS + 5)
        return _shutdown_confirmed

    runtime.set_phase("stopping")
    forced = True
    try:
        report = usb_transfer_service.shutdown()
        forced = report.forced
        logger.info(
            "有线传输停止结果: stopped=%s forced=%s 活动任务=%s reason=%s",
            report.stopped, report.forced, report.active_tasks, reason,
        )
    finally:
        # 局域网投送沿用既有收尾，不因 USB 停止失败而跳过。
        try:
            shutdown_session()
        finally:
            runtime.set_phase("interrupted" if forced else "stopped")
            with _shutdown_lock:
                _shutdown_confirmed = not forced
            _shutdown_done.set()
    return _shutdown_confirmed

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """取得应用所有权后初始化运行环境，退出时确认 USB 停止并释放所有权。"""
    try:
        owner = runtime.acquire_ownership()
    except runtime.OwnershipBusyError as exc:
        # 不生成凭据、不读取恢复记录；让启动失败并给出可操作的提示。
        logger.error("无法取得应用所有权：%s", exc)
        logger.error("请先退出另一个工具盒子窗口；若已经全部关闭，请检查是否有残留的后端或 USB 工作进程。")
        raise
    logger.info("已取得应用所有权: instance=%s launch=%s", owner.instance_id, owner.launch_id)
    try:
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

        # USB 初始化加载记录、启动后台管理线程并解析库路径；
        # 不创建 USB 子进程、不访问设备，记录回收不触碰用户传输文件。
        usb_transfer_service.initialize()
        logger.info("检测有线传输平台支持...")
        usb_platform_ok, usb_platform_reason = usb_transfer_service.probe_platform()
        capabilities.set(CAPABILITY_USB_TRANSFER, usb_platform_ok, usb_platform_reason)

        runtime.set_phase("running")
        yield
    except BaseException:
        runtime.set_phase("interrupted")
        raise
    finally:
        # 停止会等待线程与工作进程确认；放在工作线程里，避免阻塞事件循环的响应。
        try:
            await asyncio.to_thread(request_shutdown, "application_exit")
        finally:
            runtime.release_ownership()
