"""USB 本机文件操作：目录 FD 锚定、禁止链接及 macOS 排他发布。

这不是权限沙箱；不承诺抵御同权限恶意进程，也不把打开目录的移动视作路径快照。
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from toolbox_backend.core.config import settings


class LocalConflict(Exception):
    """重名、名称碰撞或类型冲突，按跳过处理。"""


class LocalFailure(Exception):
    def __init__(self, message: str, residual: str | None = None, published: bool = False) -> None:
        self.residual = residual
        self.published = published
        super().__init__(message)


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime: int
    ctime: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileIdentity:
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def same_object(self, value: os.stat_result) -> bool:
        return (self.device, self.inode) == (value.st_dev, value.st_ino)


def check_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise LocalFailure("文件名无效")
    try:
        name.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise LocalFailure("文件名不能编码为 UTF-8") from exc


def upload_name(name: str) -> None:
    check_name(name)
    if len(name) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise LocalConflict("名称含不支持的字符或超过长度预算")


def open_child_directory(parent_fd: int, name: str) -> int:
    check_name(name)
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)


def open_directory(path: str) -> int:
    """从 / 逐级打开；不借助 resolve 跟随路径中的符号链接。"""
    if not path.startswith("/") or "\x00" in path:
        raise LocalFailure("目录必须是绝对路径")
    parts = [part for part in path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise LocalFailure("路径不能包含相对跳转")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts:
            child = open_child_directory(fd, part)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def descend(root_fd: int, parts: tuple[str, ...]) -> Iterator[int]:
    fd = os.dup(root_fd)
    try:
        for part in parts:
            child = open_child_directory(fd, part)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@dataclass
class SourceAnchor:
    parent_fd: int
    name: str
    path: str
    identity: FileIdentity
    is_folder: bool

    @classmethod
    def open(cls, path: str) -> SourceAnchor:
        if path == "/":
            raise LocalFailure("不能将整个文件系统根目录作为来源")
        parent, name = os.path.split(path.rstrip("/"))
        check_name(name)
        fd = open_directory(parent or "/")
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                raise LocalConflict("只支持普通文件和目录，不跟随符号链接")
            return cls(fd, name, path, FileIdentity.from_stat(info), stat.S_ISDIR(info.st_mode))
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def parent(self, parts: tuple[str, ...]) -> Iterator[tuple[int, str]]:
        if not parts:
            yield self.parent_fd, self.name
            return
        root_info = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(root_info.st_mode) or not self.identity.same_object(root_info):
            raise LocalFailure("所选来源目录已被替换，拒绝读取")
        with descend(self.parent_fd, (self.name, *parts[:-1])) as fd:
            yield fd, parts[-1]

    @contextmanager
    def file(self, parts: tuple[str, ...], expected: FileIdentity) -> Iterator[int]:
        with self.parent(parts) as (parent_fd, name):
            check_name(name)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or FileIdentity.from_stat(info) != expected:
                raise LocalFailure("来源文件在枚举后发生变化，未开始上传")
            yield fd
        finally:
            os.close(fd)

    def close(self) -> None:
        os.close(self.parent_fd)


_rename_function = None


def rename_exclusive(parent_fd: int, source: str, target: str) -> None:
    global _rename_function
    if sys.platform != "darwin":
        raise LocalFailure("排他发布当前仅支持 macOS")
    if _rename_function is None:
        try:
            function = ctypes.CDLL(None, use_errno=True).renameatx_np
        except AttributeError as exc:
            raise LocalFailure("系统不支持排他发布，未降级为覆盖写入") from exc
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        _rename_function = function
    # Darwin 的 RENAME_EXCL；不使用较新系统才支持的附加解析标志。
    if _rename_function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 0x00000004) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise LocalConflict("发布时目标已重名，已跳过")
        raise OSError(code, os.strerror(code))


class TargetRoot:
    def __init__(self, path: str) -> None:
        self.path = path
        self.fd = open_directory(path)
        self.identities: dict[tuple[str, ...], tuple[int, int]] = {(): self._identity(self.fd)}
        self.claims: dict[tuple[tuple[str, ...], str], str] = {}
        try:
            protected = os.stat(settings.usb_transfer_root, follow_symlinks=False)
            self.protected_identity = (protected.st_dev, protected.st_ino)
            self._reject_metadata_ancestor()
            limit = os.fpathconf(self.fd, "PC_NAME_MAX")
            self.name_limit = min(255, limit) if limit > 0 else 255
        except BaseException:
            os.close(self.fd)
            raise

    @staticmethod
    def _identity(fd: int) -> tuple[int, int]:
        value = os.fstat(fd)
        return value.st_dev, value.st_ino

    def _reject_metadata_ancestor(self) -> None:
        """按目录身份阻止用户目标落进 USB 状态子树，不依赖路径字符串别名。"""
        fd = os.dup(self.fd)
        try:
            while True:
                identity = self._identity(fd)
                if identity == self.protected_identity:
                    raise LocalFailure("不能将 USB 内部状态目录作为文件接收位置")
                parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                if self._identity(parent) == identity:
                    os.close(parent)
                    break
                os.close(fd)
                fd = parent
        finally:
            os.close(fd)

    @contextmanager
    def directory(self, parts: tuple[str, ...]) -> Iterator[int]:
        fd = os.dup(self.fd)
        current: tuple[str, ...] = ()
        try:
            for part in parts:
                child = open_child_directory(fd, part)
                os.close(fd)
                fd = child
                current = (*current, part)
                if self._identity(fd) == self.protected_identity:
                    raise LocalFailure("不能向 USB 内部状态目录写入传输内容")
                if self.identities.get(current) != self._identity(fd):
                    raise LocalFailure("目标目录身份发生变化，停止该分支写入")
            yield fd
        finally:
            os.close(fd)

    def name(self, parent: tuple[str, ...], raw: str, owner: str) -> str:
        value = unicodedata.normalize("NFC", raw)
        value = "".join("_" if char in "/\\:" or ord(char) < 32 or ord(char) == 127 else char for char in value)
        value = value if value not in {"", ".", ".."} else "未命名项目"
        while value and len(value.encode("utf-8")) > self.name_limit:
            value = value[:-1]
        check_name(value)
        key = (parent, unicodedata.normalize("NFD", value).casefold())
        previous = self.claims.get(key)
        if previous is not None and previous != owner:
            raise LocalConflict("名称净化或大小写等价造成碰撞，未合并来源")
        self.claims[key] = owner
        return value

    def ensure_folder(self, parent: tuple[str, ...], name: str) -> tuple[tuple[str, ...], bool]:
        with self.directory(parent) as fd:
            created = False
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
                created = True
            except FileExistsError:
                pass
            try:
                child = open_child_directory(fd, name)
            except OSError as exc:
                if created:
                    raise LocalFailure("新建目录未能确认，目录保留", self.location((*parent, name)), True) from exc
                raise LocalConflict("同名项不是可安全复用的普通目录") from exc
            try:
                parts = (*parent, name)
                if self._identity(child) == self.protected_identity:
                    raise LocalConflict("同名目录是 USB 内部状态目录，未复用")
                self.identities[parts] = self._identity(child)
                if created:
                    try:
                        os.fsync(fd)
                    except OSError as exc:
                        raise LocalFailure("目录已创建，但同步结果未确认", self.location(parts), True) from exc
                return parts, created
            finally:
                os.close(child)

    def location(self, parts: tuple[str, ...]) -> str:
        return os.path.join(self.path, *parts)

    def receive(
        self, parent: tuple[str, ...], name: str, temporary: str, expected_size: int | None,
        download: Callable[[int], None],
    ) -> tuple[int, bool]:
        if unicodedata.normalize("NFD", name).casefold() == unicodedata.normalize("NFD", temporary).casefold():
            raise LocalConflict("目标名称与本任务临时名发生碰撞，已跳过")
        with self.directory(parent) as parent_fd:
            space = os.fstatvfs(parent_fd)
            if expected_size is not None and expected_size > space.f_bavail * space.f_frsize:
                raise LocalFailure("目标报告的可用空间不足，未开始下载")
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise LocalConflict("目标已有同名项目，已跳过")
            try:
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent_fd)
            except FileExistsError as exc:
                raise LocalFailure("同名临时项目已存在，未假定归属或删除", self.location((*parent, temporary))) from exc
            try:
                identity = FileIdentity.from_stat(os.fstat(fd))
            except OSError as exc:
                os.close(fd)
                raise LocalFailure("临时文件身份未能确认，未删除", self.location((*parent, temporary))) from exc
            published = False
            failure: BaseException | None = None
            try:
                download(fd)
                size = os.fstat(fd).st_size
                if expected_size is not None and size != expected_size:
                    raise LocalFailure("下载大小与设备报告值不符，未发布正式文件")
                os.fsync(fd)
                os.close(fd)
                fd = -1
                info = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
                if not identity.same_object(info) or not stat.S_ISREG(info.st_mode):
                    raise LocalFailure("临时文件身份变化，拒绝发布")
                rename_exclusive(parent_fd, temporary, name)
                published = True
                os.fsync(parent_fd)
                return size, expected_size is not None
            except BaseException as exc:
                failure = exc
                if published:
                    raise LocalFailure("文件已发布，但目录同步结果未确认", self.location((*parent, name)), True) from exc
                raise
            finally:
                if fd >= 0:
                    os.close(fd)
                if not published:
                    try:
                        info = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
                        if not identity.same_object(info) or not stat.S_ISREG(info.st_mode):
                            raise LocalFailure("临时文件身份已变化，未删除", self.location((*parent, temporary)))
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    except (OSError, LocalFailure) as exc:
                        raise LocalFailure("临时文件未能安全清理", self.location((*parent, temporary))) from (failure or exc)

    def close(self) -> None:
        os.close(self.fd)
