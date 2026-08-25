from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.weather_report import WeatherReport
from app.schemas.weather import WeatherReportResponse
from app.schemas.admin import AdminVerificationUpdate, AdminCategoryUpdate
from app.config import settings

router = APIRouter(prefix="/admin/weather", tags=["Admin"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == settings.ADMIN_API_KEY:
        return api_key_header
    raise HTTPException(status_code=403, detail="Could not validate credentials")

@router.patch("/{report_id}/verification", response_model=WeatherReportResponse)
async def update_verification(
    report_id: str, 
    update_data: AdminVerificationUpdate, 
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    """
    Admin endpoint to update the verification status of a report.
    """
    result = await db.execute(select(WeatherReport).where(WeatherReport.id == report_id))
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Weather report not found")
        
    report.verification_status = update_data.verification_status
    await db.commit()
    await db.refresh(report)
    
    return report

@router.patch("/{report_id}/category", response_model=WeatherReportResponse)
async def update_category(
    report_id: str, 
    update_data: AdminCategoryUpdate, 
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(get_api_key)
):
    """
    Admin endpoint to override the ML or ingestion event category.
    """
    result = await db.execute(select(WeatherReport).where(WeatherReport.id == report_id))
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Weather report not found")
        
    report.ml_event_category = update_data.event_category
    await db.commit()
    await db.refresh(report)
    
    return report
