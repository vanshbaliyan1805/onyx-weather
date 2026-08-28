from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import List
from datetime import datetime, timezone

from app.database import get_db
from app.models.weather_report import WeatherReport, MLStatusEnum
from app.schemas.weather import WeatherReportResponse
from app.schemas.ml import MLPredictionPayload, MLPredictionResponse

router = APIRouter(prefix="/ml", tags=["Machine Learning"])

@router.get("/pending", response_model=List[WeatherReportResponse])
async def get_pending_reports(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """
    Get records that need ML inference (ml_status = pending).
    Marks them as 'processing' so they aren't picked up by another worker.
    """
    # Fetch pending
    query = select(WeatherReport).where(
        WeatherReport.ml_status == MLStatusEnum.pending
    ).order_by(WeatherReport.posted_at.desc()).limit(limit)
    
    result = await db.execute(query)
    reports = result.scalars().all()
    
    if not reports:
        return []
        
    # Mark as processing
    report_ids = [r.id for r in reports]
    await db.execute(
        update(WeatherReport)
        .where(WeatherReport.id.in_(report_ids))
        .values(ml_status=MLStatusEnum.processing)
    )
    await db.commit()
    
    # Return the reports for the ML service
    return reports

@router.post("/predictions", response_model=MLPredictionResponse)
async def submit_predictions(payload: MLPredictionPayload, db: AsyncSession = Depends(get_db)):
    """
    Receive ML predictions and update the database.
    """
    updated_count = 0
    errors = []
    
    for pred in payload.predictions:
        # Check if exists
        result = await db.execute(select(WeatherReport).where(WeatherReport.id == pred.report_id))
        report = result.scalar_one_or_none()
        
        if not report:
            errors.append(f"Report ID {pred.report_id} not found")
            continue
            
        # Update fields
        report.ml_event_category = pred.ml_event_category
        report.ml_confidence = pred.ml_confidence
        report.fake_probability = pred.fake_probability
        report.duplicate_probability = pred.duplicate_probability
        report.ml_status = MLStatusEnum.completed
        report.ml_processed_at = datetime.now(timezone.utc)
        
        # Optionally allow ML model to suggest verification status if confidence is very high
        if pred.verification_status:
            report.verification_status = pred.verification_status
            
        updated_count += 1
        
    await db.commit()
    
    return MLPredictionResponse(
        updated=updated_count,
        failed=len(payload.predictions) - updated_count,
        errors=errors
    )
