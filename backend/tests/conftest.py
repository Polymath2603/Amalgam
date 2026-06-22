import os
import sys

import pytest


os.environ["K_HEADLESS"] = "1"
os.environ["K_TESTING"] = "1"
# Prevent litellm from making network requests at import time (telemetry, updates).
# litellm connects to GitHub CDN on import which can hang when offline or on restricted networks.
os.environ.setdefault("LITELLM_DISABLE_TELEMETRY", "true")


@pytest.fixture
def settings():
    import tempfile
    import json
    from backend.core.config.settings import Settings, DEFAULTS
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(DEFAULTS, f)
        tmp_path = f.name
    s = Settings(path=tmp_path)
    yield s
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


@pytest.fixture
def llm_router(settings):
    from backend.core.llm import LLMRouter
    return LLMRouter(settings=settings)


@pytest.fixture
def mcp_client():
    from backend.core.mcp.client import MCPClient
    return MCPClient()
