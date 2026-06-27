"""Tests for the read-only system status tool."""

from __future__ import annotations

import json

from openjarvis.tools.system_status import SystemStatusTool


class TestSystemStatusTool:
    def test_spec_is_read_only(self):
        tool = SystemStatusTool()

        assert tool.spec.name == "system_status"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is False
        assert tool.spec.metadata["read_only"] is True

    def test_execute_returns_local_status(self):
        result = SystemStatusTool().execute()
        payload = json.loads(result.content)

        assert result.success is True
        assert payload["machine"]
        assert payload["system"]
        assert payload["python"]
        assert payload["openjarvis_home"]
        assert "memory" in payload
        assert "hardware" in payload
        assert "nvidia_smi" in payload
        assert result.metadata["read_only"] is True

