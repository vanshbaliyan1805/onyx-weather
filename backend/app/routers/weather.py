from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_, cast, Float
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.models.weather_report import WeatherReport, MLStatusEnum
from app.schemas.weather import WeatherReportResponse, PaginatedWeatherReports

router = APIRouter(prefix="/weather", tags=["Weather Reports"])

@router.get("/", response_model=PaginatedWeatherReports)
async def get_weather_reports(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    city: Optional[str] = None,
    state: Optional[str] = None,
    event: Optional[str] = None,
    verification: Optional[str] = None,
    duplicate: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated weather reports with optional filtering.
    """
    conditions = []
    
    if city:
        conditions.append(WeatherReport.city.ilike(f"%{city}%"))
    if state:
        conditions.append(WeatherReport.state.ilike(f"%{state}%"))
    if event:
        conditions.append(WeatherReport.event_category_guess.ilike(f"%{event}%"))
    if verification:
        conditions.append(WeatherReport.verification_status == verification)
    if duplicate is not None:
        conditions.append(WeatherReport.is_likely_duplicate == duplicate)
    if from_date:
        conditions.append(WeatherReport.posted_at >= from_date)
    if to_date:
        conditions.append(WeatherReport.posted_at <= to_date)
        
    query = select(WeatherReport)
    count_query = select(func.count()).select_from(WeatherReport)
    
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))
        
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Pagination
    offset = (page - 1) * limit
    query = query.order_by(WeatherReport.posted_at.desc()).offset(offset).limit(limit)
    
    # Execute query
    result = await db.execute(query)
    items = result.scalars().all()
    
    pages = (total + limit - 1) // limit
    
    return PaginatedWeatherReports(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )

@router.get("/{report_id}", response_model=WeatherReportResponse)
async def get_weather_report(report_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific weather report by ID.
    """
    result = await db.execute(select(WeatherReport).where(WeatherReport.id == report_id))
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Weather report not found")
        
    return report
