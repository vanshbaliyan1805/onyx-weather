"""
Citizen reports connector.

The hackathon brief asks for citizen reports as a source alongside social
media/APIs/websites. A real deployment would have a mobile/web form that
POSTs directly into this pipeline's normalize+insert step. For this repo,
that intake is simulated as a JSON "queue" file
(config.CITIZEN_REPORTS_FILE) that a simple form/API would append to -
`submit_citizen_report()` below is exactly the function a Flask/FastAPI
endpoint would call.

This keeps citizen reports flowing through the *same* cleaning + DB code
path as every other source, which is the important part.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from config import CITIZEN_REPORTS_FILE, SAMPLE_DATA_DIR

SOURCE_NAME = "citizen"


def submit_citizen_report(
    text: str,
    city: str = None,
    latitude: float = None,
    longitude: float = None,
    media_urls: list = None,
    reporter_name: str = "anonymous",
) -> dict:
    """
    Call this from a web form / API endpoint to queue a new citizen report.
    Appends to the local JSON queue file (created if missing).
    """
    os.makedirs(os.path.dirname(CITIZEN_REPORTS_FILE), exist_ok=True)
    queue = []
    if os.path.exists(CITIZEN_REPORTS_FILE):
        with open(CITIZEN_REPORTS_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)

    report = {
        "id": str(uuid.uuid4()),
        "text": text,
        "city": city,
        "latitude": latitude,
        "longitude": longitude,
        "media_urls": media_urls or [],
        "reporter_name": reporter_name,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    queue.append(report)

    with open(CITIZEN_REPORTS_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    return report


def _report_to_raw(report: dict) -> dict:
    return {
        "source": SOURCE_NAME,
        "source_post_id": report["id"],
        "source_url": None,
        "author": report.get("reporter_name"),
        "text_raw": report.get("text", ""),
        "posted_at": report.get("submitted_at"),
        "location_hint": report.get("city"),
        "media_urls": report.get("media_urls", []),
        "media_type": "photo" if report.get("media_urls") else "none",
        "language": None,
        "extra": {
            "reported_latitude": report.get("latitude"),
            "reported_longitude": report.get("longitude"),
        },
    }


def fetch(demo: bool = False) -> list:
    path = os.path.join(SAMPLE_DATA_DIR, "citizen_reports_sample.json") if demo else CITIZEN_REPORTS_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        queue = json.load(f)
    return [_report_to_raw(r) for r in queue]
