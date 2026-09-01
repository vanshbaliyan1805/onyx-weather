"""
Real ML Inference Worker for Onyx Weather (DistilBERT ONLY).

This worker is responsible ONLY for computing the fake_probability.
Hybrid scoring is handled separately by models/hybrid_worker.py.

Usage:
    python models/ml_worker.py --dry-run --limit 3
    python models/ml_worker.py --dry-run --id 5413
    python models/ml_worker.py --limit 50 --batch-size 8
"""

import argparse
import os
import sys
import math
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.environ.get("MODEL_PATH", os.path.join(SCRIPT_DIR, "..", "onyx-model"))
ENV_PATH = os.path.join(SCRIPT_DIR, "..", "backend", ".env")

# ---------------------------------------------------------------------------
# Database helpers (same pattern as dummy_worker.py)
# ---------------------------------------------------------------------------
def get_db_url() -> str:
    """Load DATABASE_URL from backend/.env, converting asyncpg scheme if needed."""
    load_dotenv(ENV_PATH)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set in backend/.env")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
def load_model():
    """
    Load the DistilBERT classifier and tokenizer from local files.

    Returns (model, tokenizer, device).
    Exits with a clear error if loading fails.
    """
    try:
        import torch
        from transformers import AutoTokenizer, DistilBertForSequenceClassification
    except ImportError as e:
        print(f"ERROR: Missing dependency — {e}")
        print("Install with:")
        print("  .\\backend\\venv\\Scripts\\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu")
        print("  .\\backend\\venv\\Scripts\\python.exe -m pip install transformers safetensors")
        sys.exit(1)

    print(f"Loading model from: {MODEL_PATH}")

    if not os.path.isdir(MODEL_PATH):
        print(f"ERROR: Model directory not found: {MODEL_PATH}")
        sys.exit(1)

    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
        print("Tokenizer loaded successfully.")
    except Exception as e:
        print(f"ERROR: Failed to load tokenizer — {e}")
        sys.exit(1)

    try:
        model = DistilBertForSequenceClassification.from_pretrained(
            MODEL_PATH, local_files_only=True
        )
        print("Model loaded successfully.")
    except Exception as e:
        print(f"ERROR: Failed to load model — {e}")
        sys.exit(1)

    # Select device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    print(f"Device: {device}")

    return model, tokenizer, device


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
def predict_batch(texts: list[str], model, tokenizer, device) -> list[dict]:
    """
    Run DistilBERT inference on a batch of texts.

    Returns a list of dicts, one per text:
        {
            "fake_probability": float,
            "ml_confidence": float,
        }
    """
    import torch

    # Tokenize the entire batch at once
    encodings = tokenizer(
        texts,
        truncation=True,
        max_length=512,
        padding=True,
        return_tensors="pt",
    )

    # Move tensors to the model's device
    input_ids = encodings["input_ids"].to(device)
    attention_mask = encodings["attention_mask"].to(device)

    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs.logits  # shape: (batch_size, 2)
        probabilities = torch.softmax(logits, dim=-1)  # shape: (batch_size, 2)

    results = []
    for probs in probabilities:
        fake_prob = probs[1].item()       # P(fabricated)
        confidence = probs.max().item()   # max of the two probabilities
        results.append({
            "fake_probability": round(fake_prob, 6),
            "ml_confidence": round(confidence, 6),
        })

    return results


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------
def process_records(dry_run: bool, limit: int, batch_size: int, record_id: int = None):
    """Fetch pending records (or a specific record by ID), run DistilBERT inference, update the database."""

    # ------------------------------------------------------------------
    # 1. Load the DistilBERT model ONCE before touching the database
    # ------------------------------------------------------------------
    model, tokenizer, device = load_model()
    print()

    # ------------------------------------------------------------------
    # 2. Connect to the database
    # ------------------------------------------------------------------
    url = get_db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # --------------------------------------------------------------
            # 3. Fetch records
            # --------------------------------------------------------------
            if record_id is not None:
                cur.execute("""
                    SELECT id, text_clean, event_category_guess, author, source, measurement_check, measurement_severity
                    FROM weather_reports
                    WHERE id = %s
                """, (record_id,))
            else:
                cur.execute("""
                    SELECT id, text_clean, event_category_guess, author, source, measurement_check, measurement_severity
                    FROM weather_reports
                    WHERE ml_status = 'pending' AND source NOT IN ('openmeteo', 'rss')
                    ORDER BY id ASC
                    LIMIT %s
                """, (limit,))
            records = cur.fetchall()

            total = len(records)
            print(f"Found: {total} record(s)")
            if total == 0:
                print("Nothing to process.")
                return

            # --------------------------------------------------------------
            # 4. Process in batches
            # --------------------------------------------------------------
            num_batches = math.ceil(total / batch_size)
            completed = 0
            failed = 0

            for batch_idx in range(num_batches):
                start = batch_idx * batch_size
                end = min(start + batch_size, total)
                batch_records = records[start:end]

                print(f"\nBatch {batch_idx + 1}/{num_batches}  "
                      f"(records {start + 1}–{end})")

                # Collect texts (use empty string if text_clean is NULL)
                texts = [r["text_clean"] or "" for r in batch_records]

                # ---- Stage 1: DistilBERT inference ----
                try:
                    distilbert_preds = predict_batch(texts, model, tokenizer, device)
                except Exception as e:
                    # Entire batch failed at inference level — mark all failed
                    print(f"  Batch inference failed: {e}")
                    for r in batch_records:
                        failed += 1
                        if not dry_run:
                            _mark_failed(cur, conn, r["id"], str(e))
                    continue

                # ---- Stage 2: Store per record ----
                for rec, db_pred in zip(batch_records, distilbert_preds):
                    rec_id = rec["id"]
                    event_cat = rec["event_category_guess"]
                    
                    distilbert_fake_prob = db_pred["fake_probability"]
                    distilbert_confidence = db_pred["ml_confidence"]

                    if dry_run:
                        print(f"  Record {rec_id}:")
                        print(f"    --- DistilBERT ---")
                        print(f"    fake_probability:     {distilbert_fake_prob}")
                        print(f"    ml_confidence:        {distilbert_confidence}")
                        print(f"    ml_event_category:    {event_cat}")
                        completed += 1
                        continue

                    # Write to DB inside a savepoint so one failure doesn't
                    # roll back the entire transaction.
                    try:
                        cur.execute(f"SAVEPOINT sp_record_{rec_id}")
                        cur.execute("""
                            UPDATE weather_reports
                            SET ml_status            = 'completed',
                                ml_processed_at      = %s,
                                fake_probability     = %s,
                                ml_confidence        = %s,
                                ml_event_category    = %s,
                                duplicate_probability = NULL,
                                ml_error             = NULL
                            WHERE id = %s
                        """, (
                            datetime.now(timezone.utc),
                            distilbert_fake_prob,
                            distilbert_confidence,
                            None,  # ml_event_category not used by frontend
                            rec_id,
                        ))
                        cur.execute(f"RELEASE SAVEPOINT sp_record_{rec_id}")
                        completed += 1
                        
                        print(f"  Record {rec_id}: "
                              f"fake_prob={distilbert_fake_prob:.4f}  "
                              f"confidence={distilbert_confidence:.4f}  "
                              f"category={event_cat}")
                    except Exception as e:
                        cur.execute(f"ROLLBACK TO SAVEPOINT sp_record_{rec_id}")
                        failed += 1
                        print(f"  Record {rec_id} FAILED: {e}")
                        _mark_failed(cur, conn, rec_id, str(e))

            # --------------------------------------------------------------
            # 5. Commit or rollback
            # --------------------------------------------------------------
            print()
            if dry_run:
                conn.rollback()
                print("Dry run completed. No changes were committed to the database.")
            else:
                conn.commit()
                print("Changes committed to the database.")

            print(f"\nProcessed: {total}")
            print(f"Completed: {completed}")
            print(f"Failed:    {failed}")

    finally:
        conn.close()


def _mark_failed(cur, conn, record_id: int, error_msg: str):
    """Mark a single record as failed, tolerating DB errors."""
    try:
        cur.execute(f"SAVEPOINT sp_fail_{record_id}")
        cur.execute("""
            UPDATE weather_reports
            SET ml_status = 'failed',
                ml_error  = %s
            WHERE id = %s
        """, (error_msg, record_id))
        cur.execute(f"RELEASE SAVEPOINT sp_fail_{record_id}")
    except Exception as inner_e:
        print(f"  Could not save failure state for record {record_id}: {inner_e}")
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT sp_fail_{record_id}")
        except Exception:
            conn.rollback()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Onyx Weather — ML Inference Worker (DistilBERT ONLY)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run inference and print predictions, but do NOT write to the database.",
    )
    parser.add_argument(
        "--id",
        type=int,
        help="Process exactly one specified weather_reports.id, ignoring ml_status and limits.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of pending records to process (default: 50).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Number of records per inference batch (default: 8).",
    )
    args = parser.parse_args()

    if args.limit < 1:
        print("ERROR: --limit must be at least 1.")
        sys.exit(1)
    if args.batch_size < 1:
        print("ERROR: --batch-size must be at least 1.")
        sys.exit(1)

    process_records(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size, record_id=args.id)
