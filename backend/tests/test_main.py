import pytest
from httpx import ASGITransport, AsyncClient
from main import app

@pytest.mark.asyncio
async def test_root():
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as ac:
        response = await ac.get("/")

    assert response.status_code == 200
    assert "Welcome" in response.json()["message"]

@pytest.mark.asyncio
async def test_cors():
    import os
    import importlib
    import main
    from app.config import settings

    os.environ["FRONTEND_ORIGIN"] = "https://example-frontend.netlify.app"

    # Reload main so FRONTEND_ORIGIN is evaluated at application startup
    importlib.reload(main)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test FRONTEND_ORIGIN (Preflight)
        headers = {
            "Origin": "https://example-frontend.netlify.app",
            "Access-Control-Request-Method": "GET"
        }
        response = await ac.options("/api/v1/weather/", headers=headers)

        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-origin")
        assert allowed in ("*", "https://example-frontend.netlify.app")

        # Test an unallowed origin
        headers_bad = {
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET"
        }
        response_bad = await ac.options("/api/v1/weather/", headers=headers_bad)
        if "*" not in main.origins:
            assert response_bad.status_code == 400 or response_bad.headers.get("access-control-allow-origin") is None
