from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import openharness.cli as cli
from openharness.autopilot.types import PreflightCheck, PreflightResult


app = cli.app


def test_autopilot_preflight_cmd_prints_human_and_json(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()

    class FakeStore:
        def __init__(self, cwd):
            self.cwd = Path(cwd)

        def run_preflight(self, card):
            return PreflightResult(
                passed=False,
                checks=[
                    PreflightCheck(
                        name="auth_ok",
                        status="error",
                        reason="no auth configured for anthropic",
                        transient=True,
                        detail="Set ANTHROPIC_API_KEY or configure credentials",
                    )
                ],
                fatal=[],
                transient=[],
            )

    monkeypatch.setattr("openharness.autopilot.RepoAutopilotStore", FakeStore)

    result = runner.invoke(app, ["autopilot", "preflight", "--cwd", str(tmp_path)])
    assert result.exit_code == 0
    assert "Autopilot preflight:" in result.output
    assert "auth_ok: error" in result.output
    assert "Failure help:" in result.output

    json_result = runner.invoke(app, ["autopilot", "preflight", "--cwd", str(tmp_path), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert payload["ok"] is False
    assert payload["checks"][0]["name"] == "auth_ok"
    assert payload["diagnostics"][0]["human"] == "no auth configured for anthropic"
