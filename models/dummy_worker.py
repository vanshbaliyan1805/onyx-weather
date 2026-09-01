import argparse
import os
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timezone
import random
from dotenv import load_dotenv

def get_db_url():
    # Load .env from backend folder relative to this script
    env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
    load_dotenv(env_path)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set in backend/.env")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url

def dummy_predict(text: str) -> dict:
    """
    DUMMY prediction function.
    Uses deterministic simple heuristics based on length to simulate model outputs.
    THIS IS NOT A REAL FAKE-NEWS MODEL.
    """
    length = len(text)
    
    # Deterministic but varied outputs based on text length
    fake_prob = min(0.99, length % 100 / 100.0)
    confidence = min(0.99, (length % 50 + 50) / 100.0)
    dup_prob = min(0.99, length % 10 / 10.0)
    
    categories = ["rainfall", "flooding", "strong_wind", "other"]
    category = categories[length % len(categories)]
    
    return {
        "fake_probability": fake_prob,
        "ml_confidence": confidence,
        "ml_event_category": category,
        "duplicate_probability": dup_prob,
    }

def process_records(dry_run: bool):
    url = get_db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = False
    
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 2. Find a SMALL batch of unprocessed weather reports where ml_status = 'pending'
            # 3. Process at most 5 records
            cur.execute("""
                SELECT id, text_clean FROM weather_reports 
                WHERE ml_status = 'pending' 
                ORDER BY id ASC LIMIT 5
            """)
            records = cur.fetchall()
            
            print(f"Found: {len(records)} pending")
            
            processed = 0
            completed = 0
            failed = 0
            
            for record in records:
                processed += 1
                record_id = record["id"]
                text_clean = record["text_clean"] or ""
                
                try:
                    # 4. For each record, use text_clean as the model input
                    # 5. Implement dummy prediction
                    # 6. Produce required values
                    predictions = dummy_predict(text_clean)
                    
                    if not dry_run:
                        # 7. Update corresponding database records
                        cur.execute("""
                            UPDATE weather_reports
                            SET ml_status = 'completed',
                                ml_processed_at = %s,
                                fake_probability = %s,
                                ml_confidence = %s,
                                ml_event_category = %s,
                                duplicate_probability = %s,
                                ml_error = NULL
                            WHERE id = %s
                        """, (
                            datetime.now(timezone.utc),
                            predictions["fake_probability"],
                            predictions["ml_confidence"],
                            predictions["ml_event_category"],
                            predictions["duplicate_probability"],
                            record_id
                        ))
                    
                    completed += 1
                    print(f"  Record {record_id} processed: {predictions}")
                    
                except Exception as e:
                    # 8. If processing a record fails
                    failed += 1
                    print(f"  Record {record_id} failed: {e}")
                    if not dry_run:
                        # Update status to failed
                        try:
                            # We need to rollback the current transaction state if we hit an error 
                            # inside the transaction, but we want to save the failure state.
                            # We use a savepoint or separate connection/commit. 
                            # Since we don't want to crash the worker, we can just do a nested try.
                            # For simplicity, we just use the main cursor and hope the error wasn't a DB error.
                            cur.execute("""
                                UPDATE weather_reports
                                SET ml_status = 'failed',
                                    ml_error = %s
                                WHERE id = %s
                            """, (str(e), record_id))
                        except Exception as inner_e:
                            print(f"  Could not save failure state for {record_id}: {inner_e}")
                            conn.rollback() # reset if DB error
                            
            if dry_run:
                print("Dry run completed. No changes were committed to the database.")
                conn.rollback()
            else:
                conn.commit()
                print("Changes committed to the database.")
            
            print(f"Processed: {processed}")
            print(f"Completed: {completed}")
            print(f"Failed: {failed}")
                
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dummy ML Inference Worker")
    parser.add_argument("--dry-run", action="store_true", help="Perform predictions but do not write to the database")
    args = parser.parse_args()
    
    process_records(dry_run=args.dry_run)
