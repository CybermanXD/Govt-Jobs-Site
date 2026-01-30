"""Build a job-details JSON snapshot for Supabase storage."""

# Script entrypoint for building job details snapshot.

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server import fetch_job_details


DEFAULT_JOBS_URL = "https://tokzbiepijjdvbdtacjz.supabase.co/storage/v1/object/public/jobs-info/jobs.json"


def load_jobs(jobs_url: str) -> list[dict[str, Any]]:
    resp = requests.get(jobs_url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, list):
        return payload
    return payload.get("jobs", []) if isinstance(payload, dict) else []


def build_details_map(jobs: list[dict[str, Any]], limit: int | None = None) -> dict[str, Any]:
    details_map: dict[str, Any] = {}
    count = 0
    for job in jobs:
        job_url = job.get("url")
        if not job_url or job_url in details_map:
            continue
        details_map[job_url] = fetch_job_details(job_url)
        count += 1
        if limit is not None and count >= limit:
            break
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return {
        "updated_at": datetime.now(ist_tz).strftime("%Y-%m-%d %I:%M%p IST").lower(),
        "count": len(details_map),
        "details": details_map,
    }


def upload_to_supabase(payload: dict[str, Any]) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
    bucket = os.getenv("SUPABASE_BUCKET", "jobs-info")
    object_path = os.getenv("SUPABASE_OBJECT_PATH", "jobsDetails.json")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required for upload.")
    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{object_path}"
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "x-upsert": "true",
    }
    resp = requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=60)
    resp.raise_for_status()


def main() -> None:
    jobs_url = os.getenv("JOBS_LIST_URL", DEFAULT_JOBS_URL)
    limit_env = os.getenv("DETAILS_LIMIT")
    limit = int(limit_env) if limit_env else None
    jobs = load_jobs(jobs_url)
    payload = build_details_map(jobs, limit=limit)
    out_path = Path("jobsDetails.json")
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    if os.getenv("SUPABASE_UPLOAD") == "1":
        upload_to_supabase(payload)


if __name__ == "__main__":
    main()
