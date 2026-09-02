from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import settings
from app.routers import weather, analytics, ml, admin, pipeline
from app.database import get_db

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for Onyx Weather Big Data Platform",
    version="1.0.0",
)

# CORS configuration
import os

# Preserve existing configured CORS origins
origins = list(settings.cors_origins)

# Add local development origins if not already present
for local_origin in [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]:
    if local_origin not in origins:
        origins.append(local_origin)

# Add FRONTEND_ORIGIN from environment if set
frontend_origin = os.getenv("FRONTEND_ORIGIN")
if frontend_origin and frontend_origin not in origins:
    origins.append(frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(weather.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(ml.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
app.include_router(pipeline.router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API. Visit /docs for documentation."}

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Lightweight health check endpoint used by Render"""
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    return {"status": "ok", "database": db_status}
