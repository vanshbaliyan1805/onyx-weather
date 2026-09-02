import pytest
from httpx import AsyncClient, ASGITransport
import uuid
from main import app
from app.database import AsyncSessionLocal
from app.models.pipeline_run import PipelineRun, PipelineStatusEnum
from sqlalchemy import text

import pytest_asyncio

@pytest_asyncio.fixture(autouse=True)
async def clear_pipeline_runs():
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE pipeline_runs CASCADE"))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE pipeline_runs CASCADE"))
        await session.commit()

@pytest.mark.asyncio
async def test_get_status_idle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/pipeline/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle" # Public API returns idle when NO RUN exists
        assert data["run_id"] is None
        assert data["stages"]["ingestion"]["status"] == "pending"

@pytest.mark.asyncio
async def test_post_run_requires_api_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/pipeline/run")
        assert response.status_code == 403

@pytest.mark.asyncio
async def test_post_run_success():
    headers = {"X-API-Key": "pipeline-secret-key-change-me"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/pipeline/run", headers=headers)
        assert response.status_code == 202
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "running"
        assert data["current_stage"] == "ingestion"
        
        # Test 409 conflict when already running
        response2 = await ac.post("/api/v1/pipeline/run", headers=headers)
        assert response2.status_code == 409
        data2 = response2.json()
        assert data2["run_id"] == data["run_id"]
        assert data2["status"] == "running"
        
        # Status should show it's running
        response3 = await ac.get("/api/v1/pipeline/status")
        assert response3.status_code == 200
        data3 = response3.json()
        assert data3["run_id"] == data["run_id"]
        assert data3["status"] == "running"
