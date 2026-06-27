"""Read-only local system status tool."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _disk_snapshot(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}
    return {
        "path": str(path),
        "total_gb": round(usage.total / (1024**3), 2),
        "used_gb": round(usage.used / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
    }


def _memory_snapshot() -> dict[str, Any]:
    try:
        import psutil  # type: ignore[import]

        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent_used": mem.percent,
        }
    except Exception as exc:  # noqa: BLE001 - optional dependency/read-only probe
        windows_mem = _windows_memory_snapshot()
        if windows_mem is not None:
            windows_mem["source"] = "windows-api"
            return windows_mem
        return {"error": str(exc)}


def _windows_memory_snapshot() -> dict[str, Any] | None:
    if platform.system() != "Windows":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if not ok:
            return None

        return {
            "total_gb": round(status.ullTotalPhys / (1024**3), 2),
            "available_gb": round(status.ullAvailPhys / (1024**3), 2),
            "percent_used": float(status.dwMemoryLoad),
        }
    except Exception:  # noqa: BLE001 - status must degrade gracefully
        return None


def _hardware_snapshot() -> dict[str, Any]:
    try:
        from openjarvis.core.config import detect_hardware

        hw = detect_hardware()
        gpu = None
        if hw.gpu is not None:
            gpu = {
                "vendor": hw.gpu.vendor,
                "name": hw.gpu.name,
                "vram_gb": hw.gpu.vram_gb,
                "count": hw.gpu.count,
            }
        return {
            "cpu": hw.cpu,
            "ram_gb": hw.ram_gb,
            "gpu": gpu,
            "platform": hw.platform,
        }
    except Exception as exc:  # noqa: BLE001 - status must degrade gracefully
        return {"error": str(exc)}


def _nvidia_smi_snapshot() -> dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 - status must degrade gracefully
        return {"error": str(exc)}

    devices: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 6:
            continue
        index, name, total_mb, used_mb, utilization_pct, driver_version = parts
        try:
            total_gb = round(float(total_mb) / 1024, 2)
            used_gb = round(float(used_mb) / 1024, 2)
            utilization = float(utilization_pct)
        except ValueError:
            total_gb = used_gb = utilization = None
        devices.append(
            {
                "index": index,
                "name": name,
                "memory_total_gb": total_gb,
                "memory_used_gb": used_gb,
                "utilization_pct": utilization,
                "driver_version": driver_version,
            }
        )

    return {"devices": devices}


@ToolRegistry.register("system_status")
class SystemStatusTool(BaseTool):
    """Return a compact read-only summary of the local machine."""

    tool_id = "system_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_status",
            description=(
                "Read-only local machine status: OS, Python, OpenJarvis home, "
                "hardware, memory, and disk space. Does not modify files, "
                "services, settings, or network state."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_disk": {
                        "type": "boolean",
                        "description": "Include disk usage for key local paths.",
                    },
                    "include_hardware": {
                        "type": "boolean",
                        "description": "Include detected CPU/RAM/GPU information.",
                    },
                },
            },
            category="system",
            requires_confirmation=False,
            timeout_seconds=15.0,
            metadata={"read_only": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        include_disk = bool(params.get("include_disk", True))
        include_hardware = bool(params.get("include_hardware", True))

        home = Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))
        cwd = Path.cwd()
        payload: dict[str, Any] = {
            "machine": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cwd": str(cwd),
            "openjarvis_home": str(home),
            "memory": _memory_snapshot(),
        }
        if include_hardware:
            payload["hardware"] = _hardware_snapshot()
            payload["nvidia_smi"] = _nvidia_smi_snapshot()
        if include_disk:
            paths = [cwd, home, Path.home()]
            seen: set[str] = set()
            payload["disks"] = []
            for path in paths:
                resolved = str(path.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                payload["disks"].append(_disk_snapshot(path))

        return ToolResult(
            tool_name=self.tool_id,
            content=json.dumps(payload, indent=2, sort_keys=True),
            success=True,
            metadata={"read_only": True},
        )


__all__ = ["SystemStatusTool"]
