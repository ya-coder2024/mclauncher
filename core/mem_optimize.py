# -*- coding: utf-8 -*-
"""PCL 式内存优化：调用 Windows API 把进程工作集换出到页面文件，
释放物理内存（对启动器自身 + 运行中的 Java 游戏进程）。"""

import ctypes
import os
from ctypes import wintypes

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_SET_QUOTA = 0x0100
PROCESS_VM_OPERATION = 0x0008

_SIZET_MAX = ctypes.c_size_t(-1)


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _open(rights, pid):
    return _kernel32.OpenProcess(rights, False, pid)


def _proc_name(pid):
    h = _open(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, pid)
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    size = wintypes.DWORD(512)
    ok = _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    _kernel32.CloseHandle(h)
    return buf.value.rsplit("\\", 1)[-1].lower() if ok else ""


def working_set(pid):
    """进程当前物理内存占用（字节），失败返回 0"""
    h = _open(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, pid)
    if not h:
        return 0
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    ok = _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    _kernel32.CloseHandle(h)
    return pmc.WorkingSetSize if ok else 0


def target_pids():
    """优化目标：启动器自身 + 运行中的 Java 游戏进程"""
    arr = (wintypes.DWORD * 4096)()
    cb = wintypes.DWORD(ctypes.sizeof(arr))
    pids = [os.getpid()]
    if _psapi.EnumProcesses(ctypes.byref(arr), cb, ctypes.byref(cb)):
        count = cb.value // ctypes.sizeof(wintypes.DWORD)
        for i in range(count):
            pid = arr[i]
            if pid and pid != os.getpid() and _proc_name(pid) in ("javaw.exe", "java.exe"):
                pids.append(pid)
    return pids


def _trim(pid):
    """换出单进程工作集，返回 (前, 后) 字节"""
    before = working_set(pid)
    h = _open(PROCESS_SET_QUOTA | PROCESS_VM_OPERATION, pid)
    if not h:
        return before, before
    _kernel32.SetProcessWorkingSetSize(h, _SIZET_MAX, _SIZET_MAX)
    _kernel32.CloseHandle(h)
    return before, working_set(pid)


def optimize():
    """优化所有目标进程，返回 (释放字节, 进程数)"""
    freed, count = 0, 0
    for pid in target_pids():
        before, after = _trim(pid)
        freed += max(0, before - after)
        count += 1
    return freed, count
