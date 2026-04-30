"""Shared test fixtures."""

from __future__ import annotations

import pytest
import pytest_asyncio

from openharness.auth import storage as _auth_storage
from openharness.tasks.manager import shutdown_task_manager


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """Strip provider/auth env vars so tests don't pick up the developer's local keys."""
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENHARNESS_BASE_URL",
        "OPENHARNESS_API_FORMAT",
        "OPENHARNESS_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _disable_system_keyring(monkeypatch):
    """Skip the OS keychain during tests so developer credentials don't leak in."""
    monkeypatch.setattr(_auth_storage, "_keyring_checked", True, raising=False)
    monkeypatch.setattr(_auth_storage, "_keyring_usable", False, raising=False)
    monkeypatch.setattr(_auth_storage, "_keyring_available", lambda: False)


@pytest.fixture(autouse=True)
def _disable_claude_bridge(monkeypatch, request):
    """Stop ``load_settings`` from exporting the developer's ~/.claude tokens into env.

    Skipped for tests that explicitly exercise the Claude bridge module.
    """
    if "test_config/test_claude_bridge" in str(request.node.fspath).replace("\\", "/"):
        return

    from openharness.config import claude_bridge as _bridge

    monkeypatch.setattr(_bridge, "read_claude_settings", lambda *_a, **_kw: None)
    monkeypatch.setattr(_bridge, "apply_claude_bridge", lambda settings, **_kw: settings)


@pytest.fixture(autouse=True)
def _strip_login_shell_for_tests(monkeypatch, request):
    """Run shell subprocesses without the developer's bash login profile.

    ``bash -lc`` sources ``~/.bash_profile`` which can print extraneous
    diagnostics (e.g. JDK auto-detect errors) that pollute captured stdout.
    For tests, replace ``-lc`` with ``--noprofile --norc -c`` so output is
    deterministic regardless of the developer's shell init.

    Skipped for tests in ``test_utils/test_shell`` which assert the raw
    argv produced by :func:`resolve_shell_command`.
    """
    if "test_utils/test_shell" in str(request.node.fspath).replace("\\", "/"):
        return

    from openharness.utils import shell as _shell

    original = _shell.resolve_shell_command

    def _wrapped(command, *, platform_name=None, prefer_pty=False):
        argv = original(command, platform_name=platform_name, prefer_pty=prefer_pty)
        if "-lc" in argv:
            i = argv.index("-lc")
            # Only strip when we're invoking bash directly (not through `script`).
            if i >= 1 and argv[i - 1].endswith("bash"):
                argv = argv[: i] + ["--noprofile", "--norc", "-c"] + argv[i + 1 :]
        return argv

    monkeypatch.setattr(_shell, "resolve_shell_command", _wrapped)


@pytest_asyncio.fixture(autouse=True)
async def _reset_background_task_manager():
    yield
    await shutdown_task_manager()
