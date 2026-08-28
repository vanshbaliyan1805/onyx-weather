from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Dict, Any, List

from app.database import get_db
from app.models.weather_report import WeatherReport

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Get high-level overview statistics.
    """
    total_reports = await db.execute(select(func.count(WeatherReport.id)))
    verified_reports = await db.execute(select(func.count(WeatherReport.id)).where(WeatherReport.verification_status == "verified"))
    fake_reports = await db.execute(select(func.count(WeatherReport.id)).where(WeatherReport.verification_status == "fake"))
    
    return {
        "total_reports": total_reports.scalar() or 0,
        "verified_reports": verified_reports.scalar() or 0,
        "fake_reports": fake_reports.scalar() or 0
    }

@router.get("/events")
async def get_events_distribution(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Get distribution of event categories.
    """
    query = select(
        WeatherReport.event_category_guess, 
        func.count(WeatherReport.id).label("count")
    ).group_by(WeatherReport.event_category_guess).order_by(func.count(WeatherReport.id).desc())
    
    result = await db.execute(query)
    return [{"category": row[0], "count": row[1]} for row in result.all()]

@router.get("/states")
async def get_states_distribution(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Get report counts per state.
    """
    query = select(
        WeatherReport.state, 
        func.count(WeatherReport.id).label("count")
    ).where(WeatherReport.state != None).group_by(WeatherReport.state).order_by(func.count(WeatherReport.id).desc())
    
    result = await db.execute(query)
    return [{"state": row[0], "count": row[1]} for row in result.all()]

@router.get("/timeline")
async def get_timeline(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Get reports over time (grouped by day).
    """
    # Truncate to day using PostgreSQL's date_trunc
    query = select(
        func.date_trunc('day', WeatherReport.posted_at).label('day'),
        func.count(WeatherReport.id).label('count')
    ).group_by(func.date_trunc('day', WeatherReport.posted_at)).order_by(func.date_trunc('day', WeatherReport.posted_at))
    
    result = await db.execute(query)
    return [{"date": row[0], "count": row[1]} for row in result.all()]

@router.get("/sources")
async def get_sources_distribution(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Get report counts per source (e.g. Mastodon, Open-Meteo).
    """
    query = select(
        WeatherReport.source, 
        func.count(WeatherReport.id).label("count")
    ).group_by(WeatherReport.source).order_by(func.count(WeatherReport.id).desc())
    
    result = await db.execute(query)
    return [{"source": row[0], "count": row[1]} for row in result.all()]
