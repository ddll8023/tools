"""枚举本机可用于局域网访问的 IPv4 地址。

标准库无法列出网卡地址，因此使用 psutil 读取网卡；默认出口地址通过 UDP
socket 取得，该调用不会发出任何数据包，离线环境同样可用。

候选只保留同一局域网内其他设备的浏览器可能访问到的地址：回环、链路本地、
保留的特殊用途网段，以及隧道与虚拟网卡上的地址都会被排除——它们无法被对端
访问，留在列表里只会造成误选。
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

import psutil

from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

# 该地址仅用于让内核选出默认出口网卡，不会真正发包。
_PROBE_TARGET = ("8.8.8.8", 80)

# RFC1918 私网地址段，是局域网投送真正可用的范围。
_PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in ("192.168.0.0/16", "172.16.0.0/12", "10.0.0.0/8")
)

# 保留的特殊用途网段：不属于 RFC1918，也不可能被对端访问。
# 198.18.0.0/15 常见于代理软件与部分 VPN 的 TUN 网卡，是本功能遇到过的实际误判来源。
_SPECIAL_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in (
        "0.0.0.0/8",
        "198.18.0.0/15",
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
    )
)

# 隧道网卡：地址只在本机隧道内有效，对端浏览器无法访问。
_TUNNEL_NAME_PREFIXES = ("utun", "tun", "tap", "ppp", "ipsec", "wg")
_TUNNEL_NAME_KEYWORDS = ("vpn", "wireguard", "tailscale", "zerotier", "tunnel")

# 虚拟网卡：只服务于本机虚拟化或容器网络。
_VIRTUAL_NAME_PREFIXES = ("vmnet", "docker", "br-", "veth")
_VIRTUAL_NAME_KEYWORDS = ("virtualbox", "hyper-v", "vmware")


@dataclass(frozen=True)
class LanAddress:
    """一个可用于访问本机局域网服务的地址。"""

    address: str
    is_recommended: bool


@dataclass(frozen=True)
class _Candidate:
    """候选地址及其来源网卡。"""

    address: str
    interface: str


def _default_route_address() -> str | None:
    """返回默认出口网卡的地址，取不到时返回 None。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(_PROBE_TARGET)
        return str(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()


def _matches(address: str, networks: tuple[ipaddress.IPv4Network, ...]) -> bool:
    """判断地址是否落在给定网段内。"""
    parsed = ipaddress.IPv4Address(address)
    return any(parsed in network for network in networks)


def _is_rfc1918(address: str) -> bool:
    """判断是否为 RFC1918 私网地址；用于把局域网地址排在其他候选之前。"""
    return _matches(address, _PRIVATE_NETWORKS)


def _is_usable(address: str) -> bool:
    """排除回环、链路本地、未指定、组播与保留的特殊用途网段。"""
    try:
        parsed = ipaddress.IPv4Address(address)
    except ValueError:
        return False
    if (
        parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_unspecified
        or parsed.is_multicast
    ):
        return False
    return not _matches(address, _SPECIAL_NETWORKS)


def _is_tunnel_or_virtual(interface: str) -> bool:
    """按网卡名判断是否为隧道或虚拟网卡；这是启发式判断，仅用于排除噪声。"""
    name = interface.lower()
    if name.startswith(_TUNNEL_NAME_PREFIXES) or name.startswith(_VIRTUAL_NAME_PREFIXES):
        return True
    keywords = _TUNNEL_NAME_KEYWORDS + _VIRTUAL_NAME_KEYWORDS
    return any(keyword in name for keyword in keywords)


def _collect_candidates() -> list[_Candidate]:
    """收集启用中网卡上、对端可能访问到的 IPv4 地址。"""
    try:
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception as exc:  # 个别平台可能拒绝读取网卡信息
        logger.warning("读取网卡信息失败: %s", type(exc).__name__)
        return []

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for name, entries in interfaces.items():
        status = stats.get(name)
        if status is not None and not status.isup:
            continue
        for entry in entries:
            if entry.family != socket.AF_INET:
                continue
            address = str(entry.address)
            if address in seen or not _is_usable(address):
                continue
            # 隧道接口会带点对点对端地址，据此与网卡名一起判断。
            if entry.ptp is not None or _is_tunnel_or_virtual(name):
                continue
            seen.add(address)
            candidates.append(_Candidate(address=address, interface=name))
    return candidates


def list_lan_addresses() -> list[LanAddress]:
    """返回可用的局域网地址。

    推荐项优先取默认出口地址；该地址被排除时优先取 RFC1918 地址，仍没有则取
    排序后的首个候选，保证只要存在候选就一定有推荐项。
    """
    candidates = _collect_candidates()
    if not candidates:
        return []

    addresses = [item.address for item in candidates]
    preferred = _default_route_address()
    recommended = preferred if preferred in addresses else None
    if recommended is None:
        ordered_addresses = sorted(addresses, key=lambda item: (not _is_rfc1918(item), item))
        recommended = ordered_addresses[0]

    ordered = sorted(
        candidates,
        key=lambda item: (
            item.address != recommended,
            not _is_rfc1918(item.address),
            item.address,
        ),
    )
    return [
        LanAddress(address=item.address, is_recommended=item.address == recommended)
        for item in ordered
    ]
