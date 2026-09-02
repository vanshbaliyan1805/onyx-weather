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
    verdict: Optional[str] = None,
    flagged: Optional[bool] = None,
    duplicate: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    source: Optional[str] = None,
    exclude_source: Optional[str] = None,
    sort: Optional[str] = None,
    order: Optional[str] = "desc",
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
    if verdict:
        verdicts = [v.strip() for v in verdict.split(",") if v.strip()]
        if verdicts:
            conditions.append(WeatherReport.verdict.in_(verdicts))
    if flagged:
        conditions.append(WeatherReport.verdict.in_(["fake", "suspect"]))
    if duplicate is not None:
        conditions.append(WeatherReport.is_likely_duplicate == duplicate)
    if from_date:
        conditions.append(WeatherReport.posted_at >= from_date)
    if to_date:
        conditions.append(WeatherReport.posted_at <= to_date)
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            conditions.append(WeatherReport.source.in_(sources))
    if exclude_source:
        exclude_sources = [s.strip() for s in exclude_source.split(",") if s.strip()]
        if exclude_sources:
            conditions.append(WeatherReport.source.not_in(exclude_sources))
        
    query = select(WeatherReport)
    count_query = select(func.count()).select_from(WeatherReport)
    
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Sorting
    ALLOWED_SORT_FIELDS = {
        "hybrid_score": WeatherReport.hybrid_score,
        "posted_at": WeatherReport.posted_at,
        "ml_confidence": WeatherReport.ml_confidence,
        "fake_probability": WeatherReport.fake_probability,
        "id": WeatherReport.id
    }

    if sort is None:
        sort_column = WeatherReport.posted_at
    elif sort in ALLOWED_SORT_FIELDS:
        sort_column = ALLOWED_SORT_FIELDS[sort]
    else:
        raise HTTPException(status_code=400, detail=f"Invalid sort field: {sort}")

    # Pagination & Execution
    offset = (page - 1) * limit

    if order and order.lower() == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    query = query.offset(offset).limit(limit)
    
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
async def get_weather_report(report_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get a specific weather report by ID.
    """
    result = await db.execute(select(WeatherReport).where(WeatherReport.id == report_id))
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Weather report not found")
        
    return report
