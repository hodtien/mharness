"""Entrypoint for ``oh webui``."""

from __future__ import annotations

import logging
import os

from openharness.webui.server.config import WebUIConfig

log = logging.getLogger(__name__)


def serve(config: WebUIConfig) -> None:
    """Start the uvicorn server."""
    import uvicorn

    from openharness.webui.server.app import create_app

    if config.cwd:
        os.chdir(config.cwd)

    app = create_app(
        token=config.token,
        cwd=config.cwd,
        model=config.model,
        api_format=config.api_format,
        permission_mode=config.permission_mode,
    )

    url = f"http://{config.host}:{config.port}/?token={config.token}"
    print("\n  🌐 OpenHarness Web UI ready at:\n")
    print(f"     {url}\n")
    if config.host == "0.0.0.0":
        print("  ⚠️  Server is bound to all interfaces (public). Be careful!")
    print()

    log_level = "debug" if config.debug else "info"

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=log_level,
        # Disable access-logging noise in production.
        access_log=config.debug,
    )
