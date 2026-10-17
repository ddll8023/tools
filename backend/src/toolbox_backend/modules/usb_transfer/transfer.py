"""USB 工作进程内的选区枚举和逐项复制；不拥有队列或持久化权威状态。"""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import JsonValue

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer import local_files as local
from toolbox_backend.modules.usb_transfer import mtp
from toolbox_backend.modules.usb_transfer.schemas import (
    PlanEntry, TransferStart, UsbDirectoryEntry, UsbEntryResult, UsbProgress,
)
from toolbox_backend.modules.usb_transfer.session import ROOT_FOLDER_ID


class _BudgetStop(Exception):
    pass


@dataclass
class _Source:
    plan: PlanEntry
    anchor: local.SourceAnchor | None = None
    parts: tuple[str, ...] = ()
    identity: local.FileIdentity | None = None
    device_chain: list[UsbDirectoryEntry] | None = None


@dataclass
class _DeviceTarget:
    storage_id: int
    folder_id: int
    chain: list[UsbDirectoryEntry]


class TransferContext:
    def __init__(
        self, device: mtp.MtpDevice, start: TransferStart,
        progress: Callable[[UsbProgress], None], event: Callable[[dict[str, JsonValue]], None],
    ) -> None:
        self.device, self.start = device, start
        self.progress, self.event = progress, event
        self.sources: dict[str, _Source] = {}
        self.anchors: list[local.SourceAnchor] = []
        self.target: local.TargetRoot | None = None
        self.local_directories: dict[str, tuple[str, ...]] = {}
        self.device_directories: dict[str, _DeviceTarget] = {}
        self.results: dict[str, UsbEntryResult] = {}
        self.enumeration_complete = True
        self.connection_lost = False
        self._known_bytes = 0
        self._work = 0
        self._visited_device: set[tuple[int, int]] = set()
        self._visited_local: set[tuple[int, int]] = set()

    def _tick(self, name: str = "") -> None:
        self._work += 1
        self.progress(UsbProgress(stage="enumerating", current_name=name[:4096],
                                  discovered=len(self.sources), processed=self._work,
                                  known_bytes=self._known_bytes))

    def _add(self, source: _Source) -> None:
        if len(self.sources) >= settings.USB_TRANSFER_MAX_ENTRIES - 1:
            self.enumeration_complete = False
            plan = PlanEntry(entry_id=f"e{len(self.sources)}", raw_name=source.plan.raw_name,
                             source=source.plan.source, is_folder=source.plan.is_folder,
                             parent_entry_id=source.plan.parent_entry_id,
                             issue="failed", message="枚举预算已耗尽，剩余分支及数量未知")
            source = _Source(plan)
            self.sources[plan.entry_id] = source
            self.event({"entry": plan.model_dump(mode="json")})
            raise _BudgetStop
        plan = source.plan
        self.sources[plan.entry_id] = source
        if plan.size_bytes is not None:
            self._known_bytes += plan.size_bytes
        self.event({"entry": plan.model_dump(mode="json")})
        self._tick(plan.source)

    def _issue(self, parent: str | None, name: str, source: str, message: str, skipped: bool = False) -> None:
        # 不可编码的本机名称只用转义文本报告，不据此重新打开路径。
        name = name.encode("utf-8", errors="backslashreplace").decode("utf-8")[:4096]
        source = source.encode("utf-8", errors="backslashreplace").decode("utf-8")[:16384]
        self.enumeration_complete = False if not skipped else self.enumeration_complete
        self._add(_Source(PlanEntry(
            entry_id=f"e{len(self.sources)}", parent_entry_id=parent, raw_name=name,
            source=source, is_folder=False, issue="skipped" if skipped else "failed", message=message,
        )))

    def _mark_issue(self, source: _Source, message: str) -> None:
        self.enumeration_complete = False
        source.plan.issue, source.plan.message = "failed", message
        self.event({"entry": source.plan.model_dump(mode="json")})

    def _check_chain(
        self, storage_id: int, chain: list[UsbDirectoryEntry], cancel: threading.Event,
    ) -> UsbDirectoryEntry | None:
        """新查询目录成员关系；缓存元数据仅作会话内交叉检查，不冒充快照。"""
        parent = ROOT_FOLDER_ID
        current = None
        for expected in chain:
            mtp.check_cancel(cancel)
            ids = self.device.children(storage_id, parent, cancel)
            self._checking_progress(expected.name)
            if expected.object_id not in ids:
                raise mtp.MtpError("stale_reference", "设备对象已离开原目录，请重新浏览")
            current = self.device.metadata(expected.object_id)
            if (current.storage_id, current.parent_id, current.raw_name, current.is_folder) != (
                storage_id, parent, expected.raw_name, expected.is_folder,
            ):
                raise mtp.MtpError("stale_reference", "设备对象归属或名称发生变化")
            parent = current.object_id
            self._checking_progress(current.name)
        return current

    def _checking_progress(self, name: str) -> None:
        self._work += 1
        self.progress(UsbProgress(stage="checking", current_name=name[:4096],
                                  discovered=len(self.sources), processed=self._work))

    def plan(self, cancel: threading.Event) -> dict[str, JsonValue]:
        request = self.start.request
        self.progress(UsbProgress(stage="enumerating"))
        try:
            if request.direction == "download":
                if request.local_target is None:
                    raise mtp.MtpError("bad_request", "缺少本机目标")
                self.target = local.TargetRoot(request.local_target)
                selected = {(item.storage_id, item.object_id) for item in request.source_objects}
                for reference in request.source_objects:
                    chain = self.start.source_chains.get(f"{reference.storage_id}:{reference.object_id}")
                    if not chain or chain[-1].object_id != reference.object_id:
                        raise mtp.MtpError("bad_request", "来源对象缺少会话归属链")
                    if any((item.storage_id, item.object_id) in selected for item in chain[:-1]):
                        continue
                    try:
                        current = self._check_chain(reference.storage_id, chain, cancel)
                        if current is None:
                            raise mtp.MtpError("stale_reference", "不能复制虚拟存储根")
                        self._device_tree(current, chain, None, 0, cancel)
                    except mtp.MtpError as exc:
                        if exc.kind in {"cancelled", "disconnected", "not_open"}:
                            raise
                        self._issue(None, chain[-1].raw_name, chain[-1].name, exc.message)
            else:
                self._check_upload_target(cancel)
                opened: list[tuple[str, local.SourceAnchor | None, str, bool]] = []
                for path in request.source_paths:
                    mtp.check_cancel(cancel)
                    try:
                        anchor = local.SourceAnchor.open(path)
                        self.anchors.append(anchor)
                        opened.append((path, anchor, "", False))
                    except (OSError, local.LocalFailure, local.LocalConflict) as exc:
                        opened.append((path, None, str(exc), isinstance(exc, local.LocalConflict)))
                if len(opened) > 1 and any(anchor is not None and anchor.is_folder for _, anchor, _, _ in opened):
                    raise mtp.MtpError("bad_request", "一个任务只允许多个文件或一个目录，多目录请分别排队")
                for path, anchor, error, skipped in opened:
                    if anchor is None:
                        self._issue(None, os.path.basename(path), path, error, skipped=skipped)
                    else:
                        self._local_tree(anchor, (), None, 0, cancel)
        except _BudgetStop:
            pass
        return {"planned_count": len(self.sources), "complete": self.enumeration_complete,
                "known_bytes": self._known_bytes}

    def _device_tree(
        self, item: UsbDirectoryEntry, chain: list[UsbDirectoryEntry], parent: str | None,
        depth: int, cancel: threading.Event,
    ) -> None:
        mtp.check_cancel(cancel)
        source = _Source(PlanEntry(
            entry_id=f"e{len(self.sources)}", parent_entry_id=parent,
            raw_name=item.raw_name, source="/".join(entry.name for entry in chain)[:16384],
            is_folder=item.is_folder, size_bytes=item.size_bytes,
        ), device_chain=chain)
        key = item.storage_id, item.object_id
        if key in self._visited_device:
            source.plan.issue, source.plan.message = "failed", "设备对象重复或形成循环"
        elif depth >= settings.USB_TRANSFER_MAX_DEPTH:
            source.plan.issue, source.plan.message = "failed", "目录深度超过预算，未枚举后代"
        self._add(source)
        if source.plan.issue:
            self.enumeration_complete = False
            return
        self._visited_device.add(key)
        if not item.is_folder:
            return
        try:
            listing = self.device.list_directory(item.storage_id, item.object_id, cancel, lambda _: self._tick(source.plan.source))
        except mtp.MtpError as exc:
            if exc.kind in {"cancelled", "disconnected", "not_open"}:
                raise
            self._mark_issue(source, f"目录未能枚举：{exc.message}；后代数量未知")
            return
        for child in listing.entries:
            self._device_tree(child, [*chain, child], source.plan.entry_id, depth + 1, cancel)
        for missing in listing.missing_ids:
            self._issue(source.plan.entry_id, f"对象 {missing}", source.plan.source,
                        f"已发现对象 {missing}，但信息不可读；若为目录，其后代数量未知")

    def _local_tree(
        self, anchor: local.SourceAnchor, parts: tuple[str, ...], parent: str | None,
        depth: int, cancel: threading.Event,
    ) -> None:
        mtp.check_cancel(cancel)
        source_path = os.path.join(anchor.path, *parts)
        source: _Source | None = None
        try:
            with anchor.parent(parts) as (fd, name):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                local.upload_name(name)
                is_folder = stat.S_ISDIR(info.st_mode)
                if not is_folder and not stat.S_ISREG(info.st_mode):
                    self._issue(parent, name, source_path, "符号链接或特殊文件已跳过", skipped=True)
                    return
                source = _Source(PlanEntry(
                    entry_id=f"e{len(self.sources)}", parent_entry_id=parent,
                    raw_name=name, source=source_path, is_folder=is_folder,
                    size_bytes=None if is_folder else info.st_size,
                ), anchor=anchor, parts=parts, identity=local.FileIdentity.from_stat(info))
                key = info.st_dev, info.st_ino
                if is_folder and (key in self._visited_local or depth >= settings.USB_TRANSFER_MAX_DEPTH):
                    source.plan.issue, source.plan.message = "failed", "目录循环或深度超过预算，后代未枚举"
                    self.enumeration_complete = False
                self._add(source)
                if not is_folder or source.plan.issue:
                    return
                self._visited_local.add(key)
                child_fd = local.open_child_directory(fd, name)
            try:
                if not source.identity.same_object(os.fstat(child_fd)):
                    raise local.LocalFailure("来源目录身份发生变化")
                with os.scandir(child_fd) as entries:
                    for entry in entries:
                        self._local_tree(anchor, (*parts, entry.name), source.plan.entry_id, depth + 1, cancel)
            finally:
                os.close(child_fd)
        except (OSError, local.LocalFailure, local.LocalConflict) as exc:
            if source is not None and source.plan.entry_id in self.sources:
                self._mark_issue(source, f"来源目录未能完整枚举：{exc}")
            else:
                self._issue(parent, parts[-1] if parts else anchor.name, source_path, str(exc), isinstance(exc, local.LocalConflict))

    def _check_upload_target(self, cancel: threading.Event) -> _DeviceTarget:
        request = self.start.request
        if request.target_storage_id is None or request.target_folder_id is None:
            raise mtp.MtpError("bad_request", "缺少设备目标")
        storage = next((item for item in self.device.storages() if item.id == request.target_storage_id), None)
        if storage is None or not storage.information_complete or storage.access_capability != 0:
            raise mtp.MtpError("read_only", "设备存储只读或无法确认可写，未开始上传")
        if request.target_folder_id != ROOT_FOLDER_ID:
            current = self._check_chain(storage.id, self.start.target_chain, cancel)
            if current is None or not current.is_folder or current.object_id != request.target_folder_id:
                raise mtp.MtpError("stale_reference", "设备目标目录归属无效")
        return _DeviceTarget(storage.id, request.target_folder_id, self.start.target_chain)

    def _result(self, plan: PlanEntry, status: str, message: str = "", **fields: object) -> UsbEntryResult:
        return UsbEntryResult.model_validate({
            "entry_id": plan.entry_id, "source": plan.source, "raw_name": plan.raw_name,
            "is_folder": plan.is_folder, "size_bytes": plan.size_bytes,
            "status": status, "message": message, **fields,
        })

    def step(self, entry_id: str, cancel: threading.Event) -> UsbEntryResult:
        if entry_id in self.results:
            raise mtp.MtpError("bad_request", "工作进程拒绝重复执行同一条目")
        source = self.sources.get(entry_id)
        if source is None:
            raise mtp.MtpError("bad_request", "复制条目不存在")
        plan = source.plan
        if plan.issue:
            result = self._result(plan, plan.issue, plan.message)
        elif plan.parent_entry_id is not None and (
            plan.parent_entry_id not in self.results or self.results[plan.parent_entry_id].status != "succeeded"
        ):
            result = self._result(plan, "unexecuted", "父目录未能安全建立或复用，未执行该分支")
        else:
            try:
                mtp.check_cancel(cancel)
                if self.start.request.direction == "download":
                    result = self._download(source, cancel)
                else:
                    result = self._upload(source, cancel)
            except local.LocalConflict as exc:
                result = self._result(plan, "skipped", str(exc))
            except local.LocalFailure as exc:
                cause = exc.__cause__
                if isinstance(cause, mtp.MtpError) and cause.kind in {"disconnected", "not_open", "no_device"}:
                    self.connection_lost = True
                result = self._result(plan, "unconfirmed" if exc.residual or exc.published else "failed",
                                      str(exc), residual=exc.residual, effect=exc.published)
            except mtp.MtpError as exc:
                self.connection_lost = exc.kind in {"disconnected", "not_open", "no_device"}
                result = self._result(plan, "unexecuted" if exc.kind == "cancelled" else "failed", exc.message)
            except (OSError, UnicodeError) as exc:
                result = self._result(plan, "failed", f"本机文件操作失败：{getattr(exc, 'strerror', None) or '路径或编码不可用'}")
        self.results[entry_id] = result
        return result

    def _file_progress(self, name: str, stage: str) -> Callable[[int, int], None]:
        name = name[:4096]
        def update(sent: int, total: int) -> None:
            self.progress(UsbProgress(stage=stage, current_name=name,
                                      current_sent=sent, current_total=total or None))
        return update

    def _download(self, source: _Source, cancel: threading.Event) -> UsbEntryResult:
        plan = source.plan
        if self.target is None or not source.device_chain:
            raise local.LocalFailure("下载上下文失效")
        expected = source.device_chain[-1]
        self.progress(UsbProgress(stage="checking", current_name=plan.source[:4096]))
        current = self._check_chain(expected.storage_id, source.device_chain, cancel)
        if current is None or current.is_folder != plan.is_folder or current.size_bytes != plan.size_bytes:
            raise mtp.MtpError("stale_reference", "来源对象信息发生变化，未开始下载")
        parent = self.local_directories.get(plan.parent_entry_id, ()) if plan.parent_entry_id else ()
        if plan.parent_entry_id and plan.parent_entry_id not in self.local_directories:
            raise local.LocalFailure("目标父目录未确认")
        name = self.target.name(parent, plan.raw_name, plan.entry_id)
        destination = self.target.location((*parent, name))
        mtp.check_cancel(cancel)
        if plan.is_folder:
            parts, created = self.target.ensure_folder(parent, name)
            self.local_directories[plan.entry_id] = parts
            return self._result(plan, "succeeded", "已创建目录" if created else "复用已有普通目录",
                                destination=destination, effect=created, reused=not created)

        def download(fd: int) -> None:
            self.progress(UsbProgress(stage="checking", current_name=plan.source[:4096]))
            self.device.download(expected.object_id, fd, cancel, self._file_progress(plan.source, "downloading"))
            mtp.check_cancel(cancel)
            self.progress(UsbProgress(stage="publishing", current_name=plan.source[:4096]))

        size, checked = self.target.receive(parent, name, f".toolbox-usb-{self.start.task_id}-{plan.entry_id}.part", plan.size_bytes, download)
        return self._result(plan, "succeeded", "已排他发布", destination=destination,
                            size_bytes=size, effect=True, size_checked=checked)

    def _upload(self, source: _Source, cancel: threading.Event) -> UsbEntryResult:
        plan = source.plan
        if source.anchor is None or source.identity is None:
            raise local.LocalFailure("来源句柄已失效")
        self.progress(UsbProgress(stage="checking", current_name=plan.source[:4096]))
        root = self._check_upload_target(cancel)
        target = self.device_directories.get(plan.parent_entry_id) if plan.parent_entry_id else root
        if target is None:
            raise mtp.MtpError("stale_reference", "上传目标父目录未确认")
        self._check_chain(target.storage_id, target.chain, cancel)
        listing = self.device.list_directory(target.storage_id, target.folder_id, cancel,
                                             lambda _: self._checking_progress(plan.source))
        if not listing.complete:
            raise mtp.MtpError("list_failed", "目标目录清单不完整，未向其中写入")
        same_name = [item for item in listing.entries if item.raw_name == plan.raw_name]
        destination = f"存储 {target.storage_id}/" + "/".join([*(item.name for item in target.chain), plan.raw_name])
        if same_name:
            if plan.is_folder and len(same_name) == 1 and same_name[0].is_folder:
                with source.anchor.parent(source.parts) as (fd, name):
                    child = local.open_child_directory(fd, name)
                    try:
                        if not source.identity.same_object(os.fstat(child)):
                            raise local.LocalFailure("来源目录身份发生变化")
                    finally:
                        os.close(child)
                self.device_directories[plan.entry_id] = _DeviceTarget(target.storage_id, same_name[0].object_id, [*target.chain, same_name[0]])
                return self._result(plan, "succeeded", "复用唯一同名目录", destination=destination, reused=True)
            raise local.LocalConflict("设备已有同名项目、类型冲突或名称歧义，已跳过")
        storage = next((item for item in self.device.storages() if item.id == target.storage_id), None)
        if storage is None or not storage.information_complete or storage.access_capability != 0:
            raise mtp.MtpError("read_only", "无法确认目标存储可写")
        if storage.free_bytes is not None and (storage.free_bytes == 0 or storage.free_bytes < (plan.size_bytes or 0)):
            raise mtp.MtpError("storage_full", "设备报告的可用空间不足")
        local.upload_name(plan.raw_name)
        object_id: int | None = None
        entered_native = False
        try:
            if plan.is_folder:
                with source.anchor.parent(source.parts) as (fd, name):
                    child = local.open_child_directory(fd, name)
                    try:
                        if not source.identity.same_object(os.fstat(child)):
                            raise local.LocalFailure("来源目录身份发生变化")
                    finally:
                        os.close(child)
                mtp.check_cancel(cancel)
                self.progress(UsbProgress(stage="creating", current_name=plan.source[:4096]))
                entered_native = True
                object_id = self.device.create_folder(target.storage_id, target.folder_id, plan.raw_name, cancel)
            else:
                with source.anchor.file(source.parts, source.identity) as fd:
                    mtp.check_cancel(cancel)
                    self.progress(UsbProgress(stage="creating", current_name=plan.source[:4096]))
                    entered_native = True
                    object_id = self.device.upload(target.storage_id, target.folder_id, plan.raw_name, fd,
                                                   source.identity.size, cancel, self._file_progress(plan.source, "uploading"))
                    if local.FileIdentity.from_stat(os.fstat(fd)) != source.identity:
                        raise local.LocalFailure("上传期间来源变化，设备内容完整性未确认")
            self.progress(UsbProgress(stage="checking_result", current_name=plan.source[:4096]))
            actual = self.device.metadata(object_id)
            self._checking_progress(plan.source)
            if (actual.storage_id, actual.parent_id, actual.raw_name, actual.is_folder) != (
                target.storage_id, target.folder_id, plan.raw_name, plan.is_folder,
            ) or (not plan.is_folder and actual.size_bytes is not None and actual.size_bytes != plan.size_bytes):
                raise mtp.MtpError("result_unconfirmed", "设备报告的写入位置、名称、类型或大小不符")
            if object_id not in self.device.children(target.storage_id, target.folder_id, cancel):
                raise mtp.MtpError("result_unconfirmed", "写入对象未在目标目录中确认")
            if plan.is_folder:
                self.device_directories[plan.entry_id] = _DeviceTarget(target.storage_id, object_id, [*target.chain, actual])
            return self._result(plan, "succeeded", "协议完成并通过可获得信息的基本核对",
                                destination=destination, effect=True, object_id=object_id,
                                size_checked=not plan.is_folder and actual.size_bytes is not None)
        except (mtp.MtpError, local.LocalFailure, OSError) as exc:
            if not entered_native:
                raise
            if isinstance(exc, mtp.MtpError):
                object_id = object_id or exc.object_id
                self.connection_lost = exc.kind in {"disconnected", "not_open", "no_device"}
            residual = (f"{destination}；当前会话对象 ID {object_id}，完整性未确认" if object_id else
                        f"{destination}；可能有残留，但没有可靠对象 ID")
            return self._result(plan, "unconfirmed", str(exc), destination=destination,
                                object_id=object_id, residual=residual, effect=object_id is not None)

    def close(self) -> None:
        for anchor in self.anchors:
            anchor.close()
        self.anchors.clear()
        if self.target is not None:
            self.target.close()
            self.target = None
