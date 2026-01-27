"""Scrape jobs and emit a JSON snapshot for storage uploads."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from server import (
    dedupe_and_sort_jobs,
    MAX_JOBS_TO_CACHE,
    scrape_freejobalert_table_page,
    scrape_freejobalert_search_page,
    scrape_indgovtjobs_latest_all_india,
)


def run_scrape() -> list[dict]:
    local_jobs: list[dict] = []

    table_pages = [
        ("https://www.freejobalert.com/government-jobs/", "Govt Jobs"),
        ("https://www.freejobalert.com/bank-jobs/", "Bank Jobs"),
        ("https://www.freejobalert.com/teaching-faculty-jobs/", "Teaching Jobs"),
        ("https://www.freejobalert.com/engineering-jobs/", "Engineering Jobs"),
        ("https://www.freejobalert.com/railway-jobs/", "Railway Jobs"),
        ("https://www.freejobalert.com/police-defence-jobs/", "Police/Defence Jobs"),
        ("https://www.freejobalert.com/latest-notifications/", "Latest Notifications"),
        ("https://www.freejobalert.com/state-government-jobs/", "State Govt Jobs"),
    ]
    for url, cat in table_pages:
        local_jobs.extend(scrape_freejobalert_table_page(url, cat))

    state_pages = {
        "https://www.freejobalert.com/ap-government-jobs/": "Andhra Pradesh",
        "https://www.freejobalert.com/assam-government-jobs/": "Assam",
        "https://www.freejobalert.com/bihar-government-jobs/": "Bihar",
        "https://www.freejobalert.com/chhattisgarh-government-jobs/": "Chhattisgarh",
        "https://www.freejobalert.com/delhi-government-jobs/": "Delhi",
        "https://www.freejobalert.com/gujarat-government-jobs/": "Gujarat",
        "https://www.freejobalert.com/hp-government-jobs/": "Himachal Pradesh",
        "https://www.freejobalert.com/haryana-government-jobs/": "Haryana",
        "https://www.freejobalert.com/jharkhand-government-jobs/": "Jharkhand",
        "https://www.freejobalert.com/karnataka-government-jobs/": "Karnataka",
        "https://www.freejobalert.com/kerala-government-jobs/": "Kerala",
        "https://www.freejobalert.com/maharashtra-government-jobs/": "Maharashtra",
        "https://www.freejobalert.com/mp-government-jobs/": "Madhya Pradesh",
        "https://www.freejobalert.com/odisha-government-jobs/": "Odisha",
        "https://www.freejobalert.com/punjab-government-jobs/": "Punjab",
        "https://www.freejobalert.com/rajasthan-government-jobs/": "Rajasthan",
        "https://www.freejobalert.com/tn-government-jobs/": "Tamil Nadu",
        "https://www.freejobalert.com/telangana-government-jobs/": "Telangana",
        "https://www.freejobalert.com/uttarakhand-government-jobs/": "Uttarakhand",
        "https://www.freejobalert.com/up-government-jobs/": "Uttar Pradesh",
        "https://www.freejobalert.com/wb-government-jobs/": "West Bengal",
    }
    for url, state_name in state_pages.items():
        local_jobs.extend(scrape_freejobalert_table_page(url, state_name, state=state_name))

    search_pages = {
        "https://www.freejobalert.com/search-jobs/jobs-in-hyderabad-secunderabad/": ("Hyderabad Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-bhubaneshwar/": ("Bhubaneswar Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-new-delhi/": ("Delhi City Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-jaipur/": ("Jaipur Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-patna/": ("Patna Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-bengaluru-bangalore/": ("Bangalore Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-indore/": ("Indore Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-ludhiana/": ("Ludhiana Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-mumbai/": ("Mumbai Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-visakhapatnam/": ("Visakhapatnam Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-pune/": ("Pune Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-chennai/": ("Chennai Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-kolkata/": ("Kolkata Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-gandhinagar/": ("Gandhinagar Jobs", None),
        "https://www.freejobalert.com/search-jobs/jobs-in-lucknow/": ("Lucknow Jobs", None),
    }
    for url, (cat, forced_state) in search_pages.items():
        local_jobs.extend(scrape_freejobalert_search_page(url, category=cat, inferred_state=forced_state))

    qualification_pages = {
        "https://www.freejobalert.com/search-jobs/10th-pass-government-jobs/": "10th Pass Jobs",
        "https://www.freejobalert.com/search-jobs/8th-pass-government-jobs/": "8th Pass Jobs",
        "https://www.freejobalert.com/search-jobs/12th-pass-government-jobs/": "12th Pass Jobs",
        "https://www.freejobalert.com/search-jobs/diploma-government-jobs/": "Diploma Jobs",
        "https://www.freejobalert.com/search-jobs/iti-government-jobs/": "ITI Jobs",
        "https://www.freejobalert.com/search-jobs/btech-be-government-jobs/": "BTech/BE Jobs",
        "https://www.freejobalert.com/search-jobs/bcom-government-jobs/": "B.Com Jobs",
        "https://www.freejobalert.com/search-jobs/mba-pgdm-government-jobs/": "MBA/PGDM Jobs",
        "https://www.freejobalert.com/search-jobs/msw-government-jobs/": "MSW Jobs",
        "https://www.freejobalert.com/search-jobs/bsc-government-jobs/": "B.Sc Jobs",
        "https://www.freejobalert.com/search-jobs/msc-government-jobs/": "M.Sc Jobs",
        "https://www.freejobalert.com/search-jobs/ba-government-jobs/": "BA Jobs",
        "https://www.freejobalert.com/search-jobs/ma-government-jobs/": "MA Jobs",
        "https://www.freejobalert.com/search-jobs/any-graduate-government-jobs/": "Any Graduate Jobs",
        "https://www.freejobalert.com/search-jobs/any-post-graduate-government-jobs/": "Any Post Graduate Jobs",
    }
    for url, cat in qualification_pages.items():
        local_jobs.extend(scrape_freejobalert_search_page(url, category=cat))

    local_jobs.extend(scrape_indgovtjobs_latest_all_india())

    return dedupe_and_sort_jobs(local_jobs)[:MAX_JOBS_TO_CACHE]


def main() -> None:
    jobs = run_scrape()
    payload = {
        "updated_at": datetime.utcnow().isoformat(),
        "count": len(jobs),
        "jobs": jobs,
    }
    out_path = Path("jobs.json")
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
