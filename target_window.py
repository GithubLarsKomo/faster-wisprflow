"""Conservative Windows foreground target identity for push-to-talk insertion.

No window titles, document names, URLs or clipboard contents are collected.
The snapshot is captured before the dock changes state and checked again before
synthetic input. A missing or uninspectable identity is never a valid target.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
from pathlib import PureWindowsPath


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class TargetSnapshot:
    hwnd: int
    pid: int
    process_created_100ns: int
    focus_hwnd: int
    exe_name: str = ""

    @property
    def context_key(self) -> str:
        """Keep correction context scoped to the original target process."""
        return f"{self.pid}:{self.process_created_100ns}:{self.exe_name}"


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("flags", wt.DWORD),
        ("hwndActive", wt.HWND),
        ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND),
        ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND),
        ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


def _read_foreground() -> TargetSnapshot | None:
    """Read HWND, focused control and process birth identity; fail closed."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wt.HWND, ctypes.POINTER(wt.DWORD)
    ]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetGUIThreadInfo.argtypes = [
        wt.DWORD, ctypes.POINTER(_GUIThreadInfo)
    ]
    user32.GetGUIThreadInfo.restype = wt.BOOL
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wt.HANDLE, ctypes.POINTER(wt.FILETIME),
        ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME),
        ctypes.POINTER(wt.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return None
    pid = wt.DWORD()
    thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
    if not thread_id or not pid.value:
        return None

    gui = _GUIThreadInfo()
    gui.cbSize = ctypes.sizeof(_GUIThreadInfo)
    if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui)):
        return None
    focus_hwnd = int(gui.hwndFocus or 0)
    if not focus_hwnd:
        return None

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        return None

    try:
        created = wt.FILETIME()
        exited = wt.FILETIME()
        kernel = wt.FILETIME()
        user = wt.FILETIME()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel), ctypes.byref(user),
        ):
            return None
        creation_ticks = (int(created.dwHighDateTime) << 32) | int(
            created.dwLowDateTime
        )
        if not creation_ticks:
            return None
        name_buf = ctypes.create_unicode_buffer(32768)
        name_len = wt.DWORD(len(name_buf))
        name = ""
        if kernel32.QueryFullProcessImageNameW(
            handle, 0, name_buf, ctypes.byref(name_len)
        ):
            name = PureWindowsPath(name_buf.value).name.casefold()
        return TargetSnapshot(
            hwnd=hwnd,
            pid=pid.value,
            process_created_100ns=creation_ticks,
            focus_hwnd=focus_hwnd,
            exe_name=name,
        )
    finally:
        kernel32.CloseHandle(handle)


def capture_target() -> TargetSnapshot | None:
    """Capture only a fully inspectable target, otherwise return None."""
    try:
        return _read_foreground()
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def validate_target(expected: TargetSnapshot | None) -> bool:
    """Reject focus, window, PID or process-birth changes (including PID reuse)."""
    if expected is None or not isinstance(expected, TargetSnapshot):
        return False
    current = capture_target()
    if current is None:
        return False
    return (
        expected.hwnd == current.hwnd
        and expected.pid == current.pid
        and expected.process_created_100ns == current.process_created_100ns
        and expected.focus_hwnd == current.focus_hwnd
    )
