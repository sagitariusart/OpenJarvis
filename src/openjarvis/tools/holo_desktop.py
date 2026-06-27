"""Holo Desktop bridge tool.

Delegates visible desktop/browser tasks to the locally installed Holo harness.
"""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_DEFAULT_SCRIPT = Path(r"C:\HoloLocal\run-holo-local-msi.ps1")
_DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
_START_COMMAND = r"C:\HoloLocal\start-holo31-llama-msi.ps1"
_MAX_OUTPUT_CHARS = 12_000


def _tail(value: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:] + "\n... (output tail truncated)"


def _models_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/models"


def _server_ready(base_url: str, timeout: float = 5.0) -> tuple[bool, str]:
    url = _models_url(base_url)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = getattr(response, "status", 0)
            if 200 <= int(status) < 300:
                return True, f"Holo inference server is reachable at {url}."
            return False, f"Holo inference server returned HTTP {status} at {url}."
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return (
            False,
            "Holo inference server is not reachable at "
            f"{url}. Start it with: powershell -ExecutionPolicy Bypass -File "
            f"{_START_COMMAND}",
        )


@ToolRegistry.register("holo_desktop_run")
class HoloDesktopRunTool(BaseTool):
    """Run a bounded visible desktop/browser task through Holo."""

    tool_id = "holo_desktop_run"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="holo_desktop_run",
            description=(
                "Use the local Holo 3.1 desktop harness for visible browser or "
                "desktop UI tasks, such as opening a website, navigating pages, "
                "or clicking visible UI. Requires Holo's local inference server "
                "on 127.0.0.1:8080."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "Plain-language visible UI task for Holo to perform."
                        ),
                    },
                    "base_url": {
                        "type": "string",
                        "description": (
                            "OpenAI-compatible Holo inference endpoint. Defaults "
                            "to http://127.0.0.1:8080/v1."
                        ),
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "Maximum Holo action steps. Default 10, max 30.",
                    },
                    "max_time_seconds": {
                        "type": "integer",
                        "description": (
                            "Maximum wall-clock time for the Holo run. Default "
                            "300, max 900."
                        ),
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "When true, validate inputs and return the command "
                            "without controlling the desktop."
                        ),
                    },
                },
                "required": ["task"],
            },
            category="desktop",
            requires_confirmation=True,
            timeout_seconds=900.0,
            required_capabilities=["code:execute"],
            metadata={
                "scope": "visible_browser_desktop",
                "panic_switch": "Press Esc twice quickly to stop Holo input.",
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        task = str(params.get("task") or "").strip()
        if not task:
            return ToolResult(
                tool_name=self.tool_id,
                content="No Holo desktop task was provided.",
                success=False,
            )

        script = Path(str(params.get("script_path") or _DEFAULT_SCRIPT))
        if not script.exists():
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Holo launcher script not found: {script}",
                success=False,
            )

        base_url = str(params.get("base_url") or _DEFAULT_BASE_URL).strip()
        max_steps = _clamp_int(params.get("max_steps"), default=10, minimum=1, maximum=30)
        max_time = _clamp_int(
            params.get("max_time_seconds"),
            default=300,
            minimum=30,
            maximum=900,
        )
        dry_run = bool(params.get("dry_run", False))

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Task",
            task,
            "-BaseUrl",
            base_url,
            "-MaxSteps",
            str(max_steps),
            "-MaxTimeSeconds",
            str(max_time),
        ]

        ready, ready_message = _server_ready(base_url)
        if not ready and not dry_run:
            return ToolResult(
                tool_name=self.tool_id,
                content=ready_message,
                success=False,
                metadata={
                    "base_url": base_url,
                    "start_command": _START_COMMAND,
                    "dry_run": dry_run,
                },
            )

        if dry_run:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    "Dry run only. Holo desktop control was not started.\n"
                    f"{ready_message}\n"
                    f"Command: {command}"
                ),
                success=True,
                metadata={
                    "base_url": base_url,
                    "command": command,
                    "dry_run": True,
                    "server_ready": ready,
                },
            )

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max_time + 30,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"Holo task timed out after {max_time + 30} seconds. "
                    "Press Esc twice quickly if Holo is still controlling input."
                ),
                success=False,
                metadata={"base_url": base_url, "returncode": -1},
            )
        except OSError as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to launch Holo: {exc}",
                success=False,
                metadata={"base_url": base_url, "returncode": -1},
            )

        content = "\n".join(
            part
            for part in (
                f"Task: {task}",
                f"Exit code: {result.returncode}",
                "Safety: press Esc twice quickly to stop Holo input.",
                f"STDOUT:\n{_tail(result.stdout)}" if result.stdout else "",
                f"STDERR:\n{_tail(result.stderr)}" if result.stderr else "",
            )
            if part
        )
        return ToolResult(
            tool_name=self.tool_id,
            content=content or "(no output)",
            success=result.returncode == 0,
            metadata={
                "base_url": base_url,
                "returncode": result.returncode,
                "max_steps": max_steps,
                "max_time_seconds": max_time,
            },
        )


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


__all__ = ["HoloDesktopRunTool"]
