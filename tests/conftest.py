from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from agentdeck.config import Settings, override_settings
from agentdeck.main import app


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly selected."""
    markexpr = config.getoption("-m", default="")
    if "integration" in markexpr:
        return

    skip_integration = pytest.mark.skip(reason="use -m integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def _test_settings(tmp_path):
    """Override settings so tests use an isolated DB."""
    override_settings(
        Settings(
            state_dir=str(tmp_path),
        )
    )
    yield
    override_settings(None)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient]:
    """Async test client.

    Test modules should set app.state.session_manager
    to their own mock before using this client.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
