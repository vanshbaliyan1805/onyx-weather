from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from app.database import get_db
from app.config import settings
from app.models.pipeline_run import PipelineRun, PipelineStatusEnum

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

async def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != settings.PIPELINE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_pipeline(
    x_api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    # Check if a run is currently active
    stmt = select(PipelineRun).where(PipelineRun.status.in_([PipelineStatusEnum.pending, PipelineStatusEnum.running]))
    result = await db.execute(stmt)
    active_run = result.scalars().first()
    
    if active_run:
        public_status = "running" if active_run.status == PipelineStatusEnum.pending else active_run.status.value
        return JSONResponse(
            status_code=409,
            content={
                "run_id": str(active_run.id),
                "status": public_status,
                "current_stage": active_run.current_stage.value if active_run.current_stage and active_run.current_stage.value != "none" else None,
                "message": "A pipeline run is already in progress"
            }
        )
    
    # Create new run
    new_run = PipelineRun(status=PipelineStatusEnum.pending, current_stage=None)
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    
    return {
        "run_id": str(new_run.id),
        "status": "running", # Public API contract
        "current_stage": "ingestion", # Optimistically report ingestion
        "message": "Pipeline started"
    }

@router.get("/status")
async def get_pipeline_status(run_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    if run_id:
        stmt = select(PipelineRun).where(PipelineRun.id == run_id)
        result = await db.execute(stmt)
        run = result.scalars().first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
    else:
        stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc().nulls_last(), PipelineRun.id.desc()).limit(1)
        result = await db.execute(stmt)
        run = result.scalars().first()

    if not run:
        return {
            "run_id": None,
            "status": "idle",
            "current_stage": None,
            "stages": {
                "ingestion": {"status": "pending"},
                "ml": {"status": "pending"},
                "verification": {"status": "pending"},
                "hybrid": {"status": "pending"}
            },
            "started_at": None,
            "finished_at": None,
            "error": None
        }
        
    # Map internal DB status to public contract
    public_status = "running" if run.status == PipelineStatusEnum.pending else run.status.value
    
    stages = {
        "ingestion": {"status": "pending"},
        "ml": {"status": "pending"},
        "verification": {"status": "pending"},
        "hybrid": {"status": "pending"}
    }
    
    if run.stage_progress:
        for stage, data in run.stage_progress.items():
            if stage in stages:
                stages[stage] = data
                
    # Check if a running run is stale (no heartbeat in 5 minutes)
    if run.status in [PipelineStatusEnum.pending, PipelineStatusEnum.running]:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        hb = run.heartbeat_at or run.started_at
        if hb and (now - hb).total_seconds() > 300:
            public_status = "error"
            
    return {
        "run_id": str(run.id),
        "status": public_status,
        "current_stage": run.current_stage.value if run.current_stage and run.current_stage.value != "none" else None,
        "stages": stages,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error_message
    }
