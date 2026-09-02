import pytest
from httpx import ASGITransport, AsyncClient
from main import app

@pytest.mark.asyncio
async def test_weather_filters_all():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. source filtering
        response = await ac.get("/api/v1/weather/?source=mastodon,bluesky,citizen")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 2. exclude_source filtering
        response = await ac.get("/api/v1/weather/?exclude_source=openmeteo,rss")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 3. sorting
        response = await ac.get("/api/v1/weather/?sort=hybrid_score&order=desc")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 4. verdict comma separated
        response = await ac.get("/api/v1/weather/?verdict=fake,suspect")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 5. flagged
        response = await ac.get("/api/v1/weather/?flagged=true")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 6. invalid sort falls back to posted_at -> NOW returns 400
        response = await ac.get("/api/v1/weather/?sort=drop_table")
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

        # 7. invalid order defaults to desc
        response = await ac.get("/api/v1/weather/?order=random")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        # 8. pagination combined with filters
        response = await ac.get("/api/v1/weather/?source=mastodon&verdict=fake&page=2&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["page"] == 2
        assert data["limit"] == 5
