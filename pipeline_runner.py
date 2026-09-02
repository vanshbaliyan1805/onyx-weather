import os
import sys
import time
import subprocess
import psycopg2
import json
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv

# Ensure MODEL_PATH is set
if "MODEL_PATH" not in os.environ:
    print("ERROR: MODEL_PATH environment variable must be set.")
    sys.exit(1)

# Add models directory to sys.path so we can import the workers
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))

from ml_worker import load_model, process_records
from verify_worker import run_verification
from hybrid_worker import process_hybrid

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", ".env")

def get_db_url() -> str:
    load_dotenv(ENV_PATH)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set in backend/.env")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url

def update_run_state(conn, run_id, status=None, current_stage=None, stage_progress=None, error_message=None):
    """Updates the pipeline run state in the database."""
    now = datetime.now(timezone.utc)
    set_clauses = ["heartbeat_at = %s"]
    params = [now]
    
    if status:
        set_clauses.append("status = %s")
        params.append(status)
    if current_stage:
        set_clauses.append("current_stage = %s")
        params.append(current_stage)
    if stage_progress:
        set_clauses.append("stage_progress = %s")
        params.append(json.dumps(stage_progress))
    if error_message:
        set_clauses.append("error_message = %s")
        params.append(error_message)
    if status in ['completed', 'error']:
        set_clauses.append("finished_at = %s")
        params.append(now)
        
    params.append(run_id)
    
    sql = f"""
        UPDATE pipeline_runs
        SET {", ".join(set_clauses)}
        WHERE id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()

def run_ingestion():
    print("[INGESTION] Running ingestion fetch...")
    try:
        ingest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ingestion_pipeline")
        result = subprocess.run(
            [sys.executable, "main.py", "fetch"],
            cwd=ingest_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise Exception(f"Ingestion fetch failed with code {result.returncode}:\n{result.stderr}")
            
        # Parse output for counts if possible, else just report success
        out = result.stdout.strip().split('\n')
        last_line = out[-1] if out else "completed"
        print(f"[INGESTION] {last_line}")
        return {"status": "completed", "message": last_line}
    except Exception as e:
        print(f"[INGESTION] Exception: {e}")
        raise e

def run_pipeline_once(conn, run_id, loaded_model_bundle):
    print(f"\n--- Starting Pipeline Run {run_id} ---")
    now = datetime.now(timezone.utc)
    
    # Mark as running and set started_at
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE pipeline_runs
            SET started_at = %s, heartbeat_at = %s
            WHERE id = %s
        """, (now, now, run_id))
    conn.commit()

    stage_progress = {
        "ingestion": {"status": "pending"},
        "ml": {"status": "pending"},
        "verification": {"status": "pending"},
        "hybrid": {"status": "pending"}
    }

    try:
        # 1. Ingestion
        print("\n=> Stage: INGESTION")
        update_run_state(conn, run_id, current_stage="ingestion", stage_progress=stage_progress)
        ingestion_stats = run_ingestion()
        stage_progress["ingestion"] = ingestion_stats
        update_run_state(conn, run_id, stage_progress=stage_progress)

        # 2. ML Worker
        print("\n=> Stage: ML")
        stage_progress["ml"]["status"] = "running"
        update_run_state(conn, run_id, current_stage="ml", stage_progress=stage_progress)
        
        processed_ml, total_ml = process_records(dry_run=False, limit=100, batch_size=8, loaded_model_bundle=loaded_model_bundle)
        stage_progress["ml"] = {"status": "completed", "processed": processed_ml, "total": total_ml}
        update_run_state(conn, run_id, stage_progress=stage_progress)

        # 3. Verification Worker
        print("\n=> Stage: VERIFICATION")
        stage_progress["verification"]["status"] = "running"
        update_run_state(conn, run_id, current_stage="verification", stage_progress=stage_progress)
        
        processed_verify, total_verify = run_verification(limit=200, recheck_all=False, dry_run=False)
        stage_progress["verification"] = {"status": "completed", "processed": processed_verify, "total": total_verify}
        update_run_state(conn, run_id, stage_progress=stage_progress)
            
        # 4. Hybrid Worker
        print("\n=> Stage: HYBRID")
        stage_progress["hybrid"]["status"] = "running"
        update_run_state(conn, run_id, current_stage="hybrid", stage_progress=stage_progress)
        
        processed_hybrid, total_hybrid = process_hybrid(limit=200, recheck_all=False)
        stage_progress["hybrid"] = {"status": "completed", "processed": processed_hybrid, "total": total_hybrid}
        
        # Complete
        update_run_state(conn, run_id, status="completed", current_stage="none", stage_progress=stage_progress)
        print(f"--- Pipeline Run {run_id} Completed successfully ---")

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"--- Pipeline Run {run_id} FAILED ---\n{error_msg}")
        update_run_state(conn, run_id, status="error", error_message=str(e), stage_progress=stage_progress)


def main():
    print("Starting ONYX WEATHER local pipeline worker...")
    print("Loading ML model once at startup...")
    try:
        loaded_model_bundle = load_model()
    except Exception as e:
        print(f"Failed to load ML model: {e}")
        sys.exit(1)

    url = get_db_url()
    
    print("Pipeline ready. Listening for pending runs... Press Ctrl+C to stop.")
    poll_interval = 5
    
    try:
        while True:
            try:
                conn = psycopg2.connect(url)
                
                # Try to atomically claim a pending (idle) run
                now = datetime.now(timezone.utc)
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE pipeline_runs
                        SET status = 'running', heartbeat_at = %s
                        WHERE id = (
                            SELECT id FROM pipeline_runs 
                            WHERE status = 'pending' 
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING id
                    """, (now,))
                    row = cur.fetchone()
                
                conn.commit()

                if row:
                    run_id = row[0]
                    run_pipeline_once(conn, run_id, loaded_model_bundle)
                
            except psycopg2.Error as db_err:
                # E.g., if pipeline_runs doesn't exist yet (migrations pending)
                # print(f"Database error while polling: {db_err}")
                pass
            except Exception as e:
                print(f"Unexpected error in polling loop: {e}")
            finally:
                if 'conn' in locals() and conn:
                    conn.close()

            time.sleep(poll_interval)
            
    except KeyboardInterrupt:
        print("\nShutting down pipeline worker gracefully...")
        sys.exit(0)

if __name__ == "__main__":
    main()
