"""Measure local resources and recommend conservative model profiles.

Uses fixed argv subprocess calls (no shell) with short timeouts. Never assumes
a specific GPU variant: the recommendation is based on *measured* VRAM.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 - fixed argv, no shell
from dataclasses import dataclass


@dataclass
class ResourceReport:
    gpu_name: str | None
    gpu_total_mb: int | None
    gpu_used_mb: int | None
    ram_total_mb: int | None
    cpu_count: int
    recommended_profile: str
    note: str


def _nvidia_smi() -> tuple[str | None, int | None, int | None]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None, None
    try:
        out = subprocess.run(  # noqa: S603
            [exe, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None, None, None
    line = (out.stdout or "").strip().splitlines()
    if not line:
        return None, None, None
    parts = [p.strip() for p in line[0].split(",")]
    try:
        return parts[0], int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return parts[0] if parts else None, None, None


def _ram_total_mb() -> int | None:
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size / (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    try:  # Windows
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return int(stat.ullTotalPhys / (1024 * 1024))
    except Exception:
        return None


def measure() -> ResourceReport:
    name, total, used = _nvidia_smi()
    ram = _ram_total_mb()
    cpu = os.cpu_count() or 1
    if total is None:
        profile = "cpu-small"
        note = "No NVIDIA GPU detected (nvidia-smi unavailable). Use 3B-class text models; expect slower, bounded CPU inference."
    elif total < 6_000:
        profile = "gpu-small"
        note = f"{total} MB VRAM: use 3B-class text models (e.g. llama3.2:3b) and a small embedding model."
    elif total < 11_000:
        profile = "gpu-medium"
        note = f"{total} MB VRAM: 7-8B Q4 text models fit (e.g. qwen2.5:7b-instruct); keep model concurrency at 1."
    else:
        profile = "gpu-large"
        note = f"{total} MB VRAM: 7-14B Q4 text models fit; concurrency 1-2."
    return ResourceReport(name, total, used, ram, cpu, profile, note)
