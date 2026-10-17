"""局域网投送控制面用例：开启、查询、口令、发送与接收确认、偏好与关闭协调。

关闭序列在此统一编排：失效凭据、取消在途上传与下载、停止监听、等待读写结束、
清理未确认内容与待取件清单。停止监听本身不等于关闭完成，因此会话状态只有在
监听与在途传输都结束后才标记为已关闭。接收确认与关闭共用同一把锁，因此不会
出现确认与清理同时操作同一个文件的情况。会话到期时若仍有在途上传或下载，关闭
会顺延，直到传输结束或达到最长存活时间。
"""

from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from toolbox_backend.core import app_settings
from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.lan_transfer import isolation, receive_log
from toolbox_backend.modules.lan_transfer.addresses import list_lan_addresses
from toolbox_backend.modules.lan_transfer.schemas import (
    LanAddressItem,
    LanCleanupFailure,
    LanOutgoingItem,
    LanOutgoingListResponse,
    LanPendingItem,
    LanPendingListResponse,
    LanPreferencesResponse,
    LanReceiveRecordItem,
    LanReceiveRecordListResponse,
    LanRecoveryResponse,
    LanSessionResponse,
)
from toolbox_backend.modules.lan_transfer.server import LanWebServer
from toolbox_backend.modules.lan_transfer.session import (
    LanSession,
    SessionState,
    create_session,
    sessions,
)
from toolbox_backend.schemas.response import ErrorCode

logger = setup_logger(__name__)

# 关闭时等待在途上传停止读写的最长时间，超时只记录并交给下次启动回收。
_UPLOAD_WAIT_SECONDS = 5.0
_WAIT_POLL_SECONDS = 0.05
# 有在途传输时每次到期只顺延一小段，避免长时间占用监听端口。
_EXTEND_STEP_SECONDS = 300

_server = LanWebServer()
# 串行化启停、口令变更与接收确认，避免并发操作破坏会话状态。
_close_lock = threading.RLock()
# 本次进程启动时的遗留回收结果，供界面查询。
_last_recovery: isolation.RecoveryResult | None = None


def _device_name() -> str:
    """返回浏览器页面展示的设备名：优先用户设置，其次系统主机名。"""
    return app_settings.device_name() or socket.gethostname() or "工具盒子"


def _receive_dir() -> str:
    """返回生效的接收目录：优先用户设置，其次环境变量与默认值。"""
    return app_settings.receive_dir() or settings.lan_transfer_receive_dir


def _build_addresses(session: LanSession) -> list[LanAddressItem]:
    """把可用局域网地址转换为带会话入口链接的展示项。"""
    if session.port is None:
        return []
    return [
        LanAddressItem(
            address=item.address,
            url=f"http://{item.address}:{session.port}/s/{session.url_token}",
            is_recommended=item.is_recommended,
        )
        for item in list_lan_addresses()
    ]


def _format_time(timestamp: float) -> str:
    """把时间戳格式化为本地时间字符串。"""
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _snapshot(
    session: LanSession | None,
    message: str,
    cleanup_failures: list[LanCleanupFailure] | None = None,
) -> LanSessionResponse:
    """按会话当前状态生成响应快照；非活动会话不再暴露地址与有效期。"""
    if session is None:
        return LanSessionResponse(state=SessionState.IDLE.value, message=message)
    accepting = session.is_accepting
    budget = session.budget.snapshot()
    return LanSessionResponse(
        state=session.state.value,
        expires_at=_format_time(session.expires_at) if accepting else None,
        remaining_seconds=session.remaining_seconds if accepting else 0,
        device_name=session.device_name,
        has_passphrase=session.passphrase is not None,
        pending_count=session.pending.count(),
        used_bytes=budget.used_bytes,
        max_bytes=budget.max_bytes,
        addresses=_build_addresses(session) if accepting else [],
        free_disk_bytes=session.budget.free_disk_bytes(),
        cleanup_failures=cleanup_failures or [],
        transfer_active=session.has_active_transfer,
        message=message or session.error or "",
    )


def _pending_list(session: LanSession) -> LanPendingListResponse:
    """把待确认队列转换为响应模型。"""
    return LanPendingListResponse(
        files=[
            LanPendingItem(
                upload_id=item.upload_id,
                name=item.stored_name,
                size_bytes=item.size_bytes,
                uploaded_at=_format_time(item.uploaded_at),
            )
            for item in session.pending.list_pending()
        ]
    )


def _outgoing_list(session: LanSession) -> LanOutgoingListResponse:
    """把待取件清单转换为响应模型，并标注源文件是否仍可用。"""
    return LanOutgoingListResponse(
        files=[
            LanOutgoingItem(
                file_id=item.file_id,
                name=item.name,
                size_bytes=item.size_bytes,
                available=item.is_available,
            )
            for item in session.outgoing.list_items()
        ]
    )


def _watch_expiry(session: LanSession) -> None:
    """启动有效期监视线程，到期后按传输状态决定关闭或顺延。"""
    threading.Thread(
        target=_expire_after,
        args=(session,),
        name="lan-transfer-expiry",
        daemon=True,
    ).start()


def _expire_after(session: LanSession) -> None:
    """等待有效期结束；有在途传输时顺延，达到最长存活时间后强制关闭。"""
    while True:
        time.sleep(max(0.0, session.expires_at - time.time()))
        if sessions.current() is not session:
            return
        # 到期检查期间可能已被状态查询续期，继续等待新的有效期。
        if session.expires_at - time.time() > 0:
            continue
        if session.has_active_transfer:
            if time.time() >= session.hard_deadline:
                logger.info("局域网投送会话达到最长存活时间，强制关闭")
                stop_session("会话已达最长时限，自动关闭")
                return
            session.expires_at = time.time() + _EXTEND_STEP_SECONDS
            logger.info("投送传输进行中，会话顺延 %s 秒", _EXTEND_STEP_SECONDS)
            continue
        logger.info("局域网投送会话到期，自动关闭")
        stop_session("会话已到期，自动关闭")
        return


def _wait_for_uploads(session: LanSession) -> None:
    """等待在途上传停止文件读写；超时只记录，遗留内容由下次启动回收。"""
    deadline = time.monotonic() + _UPLOAD_WAIT_SECONDS
    while session.budget.snapshot().active_uploads > 0 and time.monotonic() < deadline:
        time.sleep(_WAIT_POLL_SECONDS)
    remaining = session.budget.snapshot().active_uploads
    if remaining:
        logger.warning("关闭会话时仍有 %s 个上传未停止", remaining)


def _cleanup_pending(session: LanSession) -> list[LanCleanupFailure]:
    """删除仍未确认的隔离内容；清理失败的残留保留占用信息并如实返回。"""
    failures: list[LanCleanupFailure] = []
    for item in session.pending.take_pending():
        try:
            item.stored_path.unlink(missing_ok=True)
        except OSError:
            failures.append(
                LanCleanupFailure(path=str(item.stored_path), size_bytes=item.size_bytes)
            )
            continue
        session.budget.release_pending_slot()
        session.budget.release(item.size_bytes)
    if failures:
        logger.warning("投送隔离内容清理失败: %s 项", len(failures))
    return failures


def start_session() -> LanSessionResponse:
    """开启投送会话；已有未结束的会话时直接返回当前状态。"""
    with _close_lock:
        current = sessions.current()
        if current is not None and current.state in (
            SessionState.STARTING,
            SessionState.ACTIVE,
            SessionState.CLOSING,
        ):
            return _snapshot(current, "投送会话已在运行")

        session = create_session(
            _device_name(),
            settings.LAN_TRANSFER_TTL_SECONDS,
            settings.LAN_TRANSFER_MAX_EXTEND_SECONDS,
        )
        sessions.install(session)
        try:
            session.port = _server.start(
                settings.LAN_TRANSFER_HOST,
                settings.LAN_TRANSFER_PORT,
            )
        except ServiceException as exc:
            session.state = SessionState.FAILED
            session.error = exc.message
            sessions.clear()
            raise

        session.state = SessionState.ACTIVE
        _watch_expiry(session)
        logger.info(
            "投送会话已开启: port=%s ttl=%s",
            session.port,
            settings.LAN_TRANSFER_TTL_SECONDS,
        )
        return _snapshot(session, "投送已开启")


def get_status() -> LanSessionResponse:
    """返回当前会话状态；无会话时返回空闲状态，到期时按传输状态关闭或顺延。"""
    session = sessions.current()
    if session is None:
        return _snapshot(None, "投送未开启")
    if session.is_accepting and session.remaining_seconds <= 0:
        if not session.has_active_transfer:
            return stop_session("会话已到期，自动关闭")
        if time.time() >= session.hard_deadline:
            return stop_session("会话已达最长时限，自动关闭")
        session.expires_at = time.time() + _EXTEND_STEP_SECONDS
    return _snapshot(session, "")


def list_pending() -> LanPendingListResponse:
    """返回当前等待确认的接收内容。"""
    session = sessions.current()
    if session is None:
        return LanPendingListResponse()
    return _pending_list(session)


def accept_pending(upload_id: str) -> LanPendingListResponse:
    """把待确认内容移入接收目录；失败时退回待确认状态并保留隔离文件。"""
    with _close_lock:
        session = sessions.current()
        if session is None:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "投送未开启")

        item = session.pending.claim(upload_id, lambda: session.is_accepting)
        try:
            receive_dir = Path(_receive_dir())
            receive_dir.mkdir(parents=True, exist_ok=True)
            destination = isolation.unique_destination(receive_dir, item.stored_name)
            shutil.move(str(item.stored_path), str(destination))
        except ServiceException:
            session.pending.release(upload_id)
            raise
        except OSError as exc:
            session.pending.release(upload_id)
            raise ServiceException(
                ErrorCode.INTERNAL_ERROR,
                f"写入接收目录失败：{exc.strerror or '未知原因'}",
            ) from exc

        session.pending.discard(upload_id)
        session.budget.release_pending_slot()
        session.budget.release(item.size_bytes)
        receive_log.append(item.stored_name, item.size_bytes, str(destination))
        logger.info("投送内容已接收: 文件=%s", item.stored_name)
        return _pending_list(session)


def reject_pending(upload_id: str) -> LanPendingListResponse:
    """拒绝待确认内容并删除其隔离文件。"""
    with _close_lock:
        session = sessions.current()
        if session is None:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "投送未开启")

        item = session.pending.claim(upload_id, lambda: session.is_accepting)
        try:
            item.stored_path.unlink(missing_ok=True)
        except OSError as exc:
            session.pending.release(upload_id)
            raise ServiceException(ErrorCode.INTERNAL_ERROR, "删除待接收文件失败") from exc

        session.pending.discard(upload_id)
        session.budget.release_pending_slot()
        session.budget.release(item.size_bytes)
        logger.info("投送内容已拒绝: 文件=%s", item.stored_name)
        return _pending_list(session)


def list_outgoing() -> LanOutgoingListResponse:
    """返回当前待取件清单。"""
    session = sessions.current()
    if session is None:
        return LanOutgoingListResponse()
    return _outgoing_list(session)


def add_outgoing(paths: list[str]) -> LanOutgoingListResponse:
    """把工具页选中的本机文件加入待取件清单。"""
    with _close_lock:
        session = sessions.current()
        if session is None or not session.is_accepting:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "请先开启投送会话")

        added = session.outgoing.register(paths)
        if added:
            logger.info("待取件清单新增 %s 个文件", len(added))
        return _outgoing_list(session)


def remove_outgoing(file_id: str) -> LanOutgoingListResponse:
    """从待取件清单移除文件。"""
    with _close_lock:
        session = sessions.current()
        if session is None or not session.is_accepting:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "请先开启投送会话")

        if not session.outgoing.remove(file_id):
            raise ServiceException(ErrorCode.DATA_NOT_FOUND, "该文件已不在待取件清单中")
        return _outgoing_list(session)


def _validate_receive_dir(raw: str) -> str:
    """校验接收目录为绝对路径且可写；不存在时先创建，并用写入探测确认。"""
    if not os.path.isabs(raw):
        raise ServiceException(ErrorCode.PARAM_ERROR, "接收目录必须是绝对路径")

    directory = Path(os.path.abspath(raw))
    probe = directory / f".toolbox-write-test-{os.getpid()}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            f"接收目录不可写：{exc.strerror or '未知原因'}",
        ) from exc
    return str(directory)


def get_preferences() -> LanPreferencesResponse:
    """返回生效的设备名、接收目录与自定义状态。"""
    customized = app_settings.customized_fields()
    return LanPreferencesResponse(
        device_name=_device_name(),
        receive_dir=_receive_dir(),
        default_device_name=socket.gethostname() or "工具盒子",
        default_receive_dir=settings.lan_transfer_receive_dir,
        is_customized=bool(customized),
    )


def update_preferences(
    device_name: str | None = None,
    receive_dir: str | None = None,
) -> LanPreferencesResponse:
    """更新设备名与接收目录；空字符串表示清除该项并回退默认值。"""
    normalized_dir: str | None = None
    if receive_dir is not None:
        cleaned = receive_dir.strip()
        normalized_dir = _validate_receive_dir(cleaned) if cleaned else ""

    app_settings.update(device_name=device_name, receive_dir=normalized_dir)
    return get_preferences()


def list_receive_records() -> LanReceiveRecordListResponse:
    """按接收时间倒序返回接收记录。"""
    return LanReceiveRecordListResponse(
        records=[
            LanReceiveRecordItem(
                name=record.name,
                size_bytes=record.size_bytes,
                received_at=_format_time(record.received_at),
                destination=record.destination,
            )
            for record in receive_log.list_recent()
        ]
    )


def recover_on_startup() -> None:
    """回收上次异常终止遗留的隔离内容，并暂存结果供界面查询。"""
    global _last_recovery
    _last_recovery = isolation.recover_leftovers()


def get_last_recovery() -> LanRecoveryResponse:
    """返回本次进程启动时的遗留回收结果。"""
    if _last_recovery is None:
        return LanRecoveryResponse(recovered=False)
    return LanRecoveryResponse(
        recovered=True,
        removed_files=_last_recovery.removed_files,
        removed_bytes=_last_recovery.removed_bytes,
        failures=list(_last_recovery.failures),
    )


def stop_session(message: str = "投送已停止") -> LanSessionResponse:
    """按关闭序列停止会话并返回关闭后的状态。"""
    with _close_lock:
        session = sessions.current()
        if session is None:
            return _snapshot(None, "投送未开启")

        # 1. 进入关闭中：访问凭据立即失效，数据面拒绝新的上传与确认。
        session.state = SessionState.CLOSING

        # 2. 取消在途上传与下载；上传方在下一块数据处退出并自行清理未完成内容。
        cancelled = session.in_flight.cancel_all()
        if cancelled:
            logger.info("关闭会话时取消了 %s 个在途操作", cancelled)

        # 3. 停止监听；必要时的强制断开会让下载流提前结束并关闭文件句柄。
        #    在途上传的目标文件不在待确认队列中，另行等待其释放读写。
        _server.stop()
        _wait_for_uploads(session)

        # 4. 清理未确认内容并释放预算；已接收的文件不参与删除。
        failures = _cleanup_pending(session)

        # 5. 释放待取件清单；文件本体属于用户自己的目录，不做任何删除。
        session.outgoing.clear()

        # 6. 标记已关闭并释放会话凭据。
        session.state = SessionState.CLOSED
        snapshot = _snapshot(session, message, failures)
        sessions.clear()
        logger.info("投送会话已关闭")
        return snapshot


def set_passphrase(passphrase: str) -> LanSessionResponse:
    """设置或清除访问口令；变更后已进入的浏览器需要重新通过口令。"""
    with _close_lock:
        session = sessions.current()
        if session is None or not session.is_accepting:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "请先开启投送会话")

        cleaned = passphrase.strip()
        if cleaned != (session.passphrase or ""):
            session.passphrase = cleaned or None
            session.rotate_cookie_secret()
        return _snapshot(session, "访问口令已更新" if session.passphrase else "访问口令已清除")


def shutdown_session() -> None:
    """应用退出时关闭会话；不向调用方抛出异常。"""
    try:
        stop_session("应用已退出")
    except Exception as exc:  # 退出路径不阻塞，异常只记录类型
        logger.warning("退出时关闭投送会话失败: %s", type(exc).__name__)
