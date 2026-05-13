"""Tests for autopilot code-review verification step."""

from __future__ import annotations

from openharness.autopilot.service import (
    _DEFAULT_AUTOPILOT_POLICY,
    _DEFAULT_VERIFICATION_POLICY,
    _parse_review_severity,
)


def test_default_policy_includes_code_review_block():
    assert "code_review" in _DEFAULT_VERIFICATION_POLICY
    cr = _DEFAULT_VERIFICATION_POLICY["code_review"]
    assert cr["enabled"] is True
    assert cr["agent"] == "code-reviewer"
    assert cr["block_on"] == ["critical", "high", "medium", "low"]


def test_default_policy_includes_repair_architect_block():
    repair = _DEFAULT_AUTOPILOT_POLICY["repair"]
    assert repair["architect_enabled"] is True
    assert repair["architect_agent"] == "architect"
    assert repair["architect_model"] == "claude-architect"
    assert repair["architect_on_severity"] == ["critical", "high", "medium", "low"]


def test_parse_severity_detects_critical():
    text = "Found a hardcoded API key.\nSeverity: CRITICAL"
    assert _parse_review_severity(text) == "critical"


def test_parse_severity_detects_high():
    assert _parse_review_severity("Severity: HIGH") == "high"


def test_parse_severity_detects_medium():
    assert _parse_review_severity("Severity: MEDIUM") == "medium"


def test_parse_severity_detects_low():
    assert _parse_review_severity("Severity: LOW") == "low"


def test_parse_severity_returns_none_when_absent():
    assert _parse_review_severity("All good. No issues.") == "none"


def test_parse_severity_prefers_explicit_severity_line():
    text = "Severity: NONE\nSummary: No CRITICAL issues — not blocking."
    assert _parse_review_severity(text) == "none"


def test_parse_severity_returns_none_without_explicit_line():
    assert _parse_review_severity("No CRITICAL issues found.") == "none"


def test_parse_severity_handles_empty_input():
    assert _parse_review_severity("") == "none"
    assert _parse_review_severity(None) == "none"  # type: ignore[arg-type]


def test_parse_severity_detects_explicit_critical_even_with_other_words():
    text = "Severity: CRITICAL\nFindings: also mentions HIGH style issue and LOW typo."
    assert _parse_review_severity(text) == "critical"
