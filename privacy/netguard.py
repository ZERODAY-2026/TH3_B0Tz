"""In-process network guard built on Python audit hooks (PEP 578).

Once installed, every socket connect, sendto, DNS lookup and urllib request
made anywhere in this Python process (our code or any dependency) is
recorded. In "block" mode any destination that is not loopback raises
PermissionError before a packet is sent, so the process cannot reach the
network even if the machine is online.

Audit hooks cannot be removed once added, so install() is meant for a
dedicated proof process (privacy/capture.py), not the app itself.
"""
from __future__ import annotations

import ipaddress
import socket
import sys
import time
from dataclasses import asdict, dataclass

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


@dataclass
class NetEvent:
    t: float
    event: str
    target: str
    loopback: bool
    blocked: bool


events: list[NetEvent] = []
_mode = "record"
_installed = False


def is_loopback(host: object) -> bool:
    if host is None:
        return False
    if isinstance(host, (bytes, bytearray)):
        host = host.decode(errors="replace")
    host = str(host).strip("[]")
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _target(event: str, args: tuple) -> tuple[str, bool] | None:
    """(printable target, loopback?) for the events we care about."""
    if event in ("socket.connect", "socket.sendto"):
        sock, addr = args[0], args[1]
        if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
            return f"unix:{addr}", True           # local IPC, never leaves the machine
        if isinstance(addr, tuple):
            return f"{addr[0]}:{addr[1]}", is_loopback(addr[0])
        return str(addr), False
    if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                 "socket.gethostbyaddr"):
        host = args[0]
        return f"dns:{host}", is_loopback(host)
    if event == "urllib.Request":
        url = str(args[0])
        host = url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
        return url, is_loopback(host)
    return None


def _hook(event: str, args: tuple) -> None:
    hit = _target(event, args) if event.startswith(("socket.", "urllib.")) else None
    if hit is None:
        return
    target, loop = hit
    blocked = _mode == "block" and not loop
    events.append(NetEvent(time.time(), event, target, loop, blocked))
    if blocked:
        raise PermissionError(f"LegalLens privacy guard blocked network access: {event} {target}")


def install(mode: str = "record") -> None:
    """mode: "record" logs everything; "block" also refuses non-loopback."""
    global _mode, _installed
    if mode not in ("record", "block"):
        raise ValueError("mode must be 'record' or 'block'")
    _mode = mode
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def summary() -> dict:
    outside = [e for e in events if not e.loopback]
    return {
        "mode": _mode,
        "events_total": len(events),
        "loopback_events": len(events) - len(outside),
        "non_loopback_events": len(outside),
        "non_loopback": [asdict(e) for e in outside],
        "distinct_targets": sorted({e.target for e in events}),
    }
