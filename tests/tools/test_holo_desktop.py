from __future__ import annotations

from pathlib import Path

from openjarvis.tools.holo_desktop import HoloDesktopRunTool, _clamp_int, _models_url


def test_models_url_normalizes_base_url():
    assert _models_url("http://127.0.0.1:8080/v1/") == (
        "http://127.0.0.1:8080/v1/models"
    )


def test_clamp_int_bounds_values():
    assert _clamp_int(None, default=10, minimum=1, maximum=30) == 10
    assert _clamp_int("999", default=10, minimum=1, maximum=30) == 30
    assert _clamp_int("-1", default=10, minimum=1, maximum=30) == 1


def test_dry_run_returns_command_without_desktop_control(tmp_path, monkeypatch):
    script = tmp_path / "run-holo-local-msi.ps1"
    script.write_text("param()\n", encoding="utf-8")

    monkeypatch.setattr(
        "openjarvis.tools.holo_desktop._server_ready",
        lambda base_url: (True, "ready"),
    )

    result = HoloDesktopRunTool().execute(
        task="Open https://example.com",
        script_path=str(script),
        dry_run=True,
        max_steps=99,
        max_time_seconds=9999,
    )

    assert result.success is True
    assert result.metadata["dry_run"] is True
    assert result.metadata["server_ready"] is True
    assert "-Task" in result.metadata["command"]
    assert "Open https://example.com" in result.metadata["command"]
    assert result.metadata["command"][result.metadata["command"].index("-MaxSteps") + 1] == "30"
    assert result.metadata["command"][
        result.metadata["command"].index("-MaxTimeSeconds") + 1
    ] == "900"


def test_missing_server_blocks_real_run(tmp_path, monkeypatch):
    script = tmp_path / "run-holo-local-msi.ps1"
    script.write_text("param()\n", encoding="utf-8")

    monkeypatch.setattr(
        "openjarvis.tools.holo_desktop._server_ready",
        lambda base_url: (False, "server missing"),
    )

    result = HoloDesktopRunTool().execute(
        task="Open https://example.com",
        script_path=str(script),
    )

    assert result.success is False
    assert "server missing" in result.content
