"""
Flask server that provides real‑time government job data and job details.

This server scrapes a couple of well‑known government job portals (FreeJobAlert
and IndGovtJobs) and exposes the results as JSON.  It also exposes an
endpoint for retrieving detailed information about a specific job post when
provided with the URL to the post.  The scraped data includes essential
fields such as job title, recruiting board/organisation, minimum
qualification, last application date, and the source website.  By running
this server alongside the front‑end, the job portal can fetch live job
information and display full job details on demand.

Dependencies:
  * Flask – micro web framework for Python
  * requests – for HTTP requests
  * beautifulsoup4 – for HTML parsing

Install dependencies via pip:
    pip install flask requests beautifulsoup4

To run the server:
    python server.py

The API exposes the following endpoints:
  GET /api/jobs
    Returns a JSON list of job postings scraped from FreeJobAlert and
    IndGovtJobs.  Each item has keys: title, board, qualification,
    lastDate (ISO string), source, and url.

  GET /api/job_details?url=<job_url>
    Fetches the provided job URL and attempts to extract a summary of the
    post.  The response includes the raw HTML text and, when available,
    structured details such as eligibility criteria, age limit, and
    important dates.

NOTE: The scraping logic is simplified and intended as a proof of concept.
      Real websites may change their structure over time, requiring updates
      to the parsing routines.
"""

from __future__ import annotations

from datetime import datetime
import re
import json
import logging
from typing import List, Dict, Any, Tuple, Optional, Set

import os
import requests
import threading
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, abort
import time

# Configure Flask to serve static front‑end files from the "website" directory.
# Resolve the absolute path to the "website" directory.  When run from
# arbitrary working directories this ensures Flask can locate the static
# files (index.html, style.css, script.js, etc.).
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = os.path.join(ROOT_DIR, "website")

# Configure the Flask app.  The static_url_path is left empty so that
# static files (CSS, JS) are served relative to the root.  The static_folder
# uses an absolute path to avoid 404s when the app is started from a
# different working directory.
app = Flask(__name__, static_folder=STATIC_PATH, static_url_path="")

logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# CORS support
#
# Allow the API endpoints to be called from different origins (e.g. file://)
# by adding appropriate CORS headers on every response.  This permits the
# front‑end to fetch data from http://127.0.0.1:5000 even when the page is
# loaded from the local filesystem.
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ----------------------------------------------------------------------------
# Background job caching and periodic scraping infrastructure
#
# To improve responsiveness of the API and prevent blocking on every request,
# the server maintains an in‑memory cache (`jobs_cache`) containing the
# latest scraped jobs.  A background thread performs the full scrape on
# startup (or on the first API call if the server is started lazily) and
# then refreshes the cache every `REFRESH_INTERVAL_SEC` seconds.  During
# a refresh, the existing jobs remain available to the API so that
# clients continue to receive data without interruption.  Only when the
# refresh completes successfully does the cache get replaced.  A
# `jobs_loading` flag indicates when a refresh is in progress.

# Global cache for jobs scraped.  Protected by scrape_lock when modified.
jobs_cache: List[Dict[str, Any]] = []
jobs_loaded: bool = False  # Set True after the first full scrape completes
jobs_loading: bool = False  # True while a background scrape is running
scrape_thread_started: bool = False  # Ensures we only start the periodic thread once
scrape_lock = threading.Lock()

# Refresh interval for periodic scraping (in seconds).  The scraper will
# run in the background every 10 minutes by default.  Adjust this value
# if you need more or less frequent updates.
REFRESH_INTERVAL_SEC = 10 * 60

# Maximum number of jobs to keep in the cache.  After scraping and
# deduplicating, the cache will be truncated to this size, keeping the
# most recent postings first.
MAX_JOBS_TO_CACHE = 6000

# Optional persistence for the in-memory cache so restarts don't wipe data.
CACHE_PERSIST_PATH = os.path.join(ROOT_DIR, "jobs_cache.json")

def default_last_date_key(job: Dict[str, Any]) -> str:
    """Default sort key for job deadlines (closest deadline first)."""
    return job.get("lastDate") or "9999-12-31"

def dedupe_and_sort_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate jobs by URL/title and sort by nearest last date first."""
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for job in jobs:
        key = job.get("url") or job.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    deduped.sort(key=default_last_date_key)
    return deduped

def persist_jobs_cache(jobs: List[Dict[str, Any]]) -> None:
    """Persist the current cache to disk for fast startup."""
    try:
        payload = {
            "updated_at": datetime.utcnow().isoformat(),
            "jobs": jobs,
        }
        with open(CACHE_PERSIST_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logging.error("Failed to persist jobs cache: %s", e)

def load_jobs_cache_from_disk() -> bool:
    """Load the persisted cache from disk into memory, if available."""
    global jobs_cache, jobs_loaded
    if not os.path.exists(CACHE_PERSIST_PATH):
        return False
    try:
        with open(CACHE_PERSIST_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            cached_jobs = payload
        else:
            cached_jobs = payload.get("jobs", [])
        if not isinstance(cached_jobs, list):
            return False
        deduped = dedupe_and_sort_jobs(cached_jobs)[:MAX_JOBS_TO_CACHE]
        with scrape_lock:
            jobs_cache = deduped
            jobs_loaded = True
        logging.info("Loaded %d cached jobs from disk", len(deduped))
        return True
    except Exception as e:
        logging.error("Failed to load cached jobs from disk: %s", e)
        return False

def update_cache_snapshot(jobs: List[Dict[str, Any]], mark_loaded: bool) -> None:
    """Update the global cache with deduped, sorted jobs and persist to disk."""
    global jobs_cache, jobs_loaded
    deduped = dedupe_and_sort_jobs(jobs)[:MAX_JOBS_TO_CACHE]
    with scrape_lock:
        jobs_cache = deduped
        jobs_loaded = mark_loaded
    persist_jobs_cache(deduped)

def ensure_scrape_thread_started() -> None:
    """Start the periodic scraping thread once."""
    global scrape_thread_started
    if scrape_thread_started:
        return
    scrape_thread_started = True
    threading.Thread(target=periodic_scrape_loop, daemon=True).start()

# Load persisted cache early for faster first response.
load_jobs_cache_from_disk()

def periodic_scrape_loop() -> None:
    """Run the full scrape periodically.

    This function is intended to run in a dedicated background thread.  It
    calls run_full_scrape() immediately on startup and then sleeps for
    REFRESH_INTERVAL_SEC seconds before each subsequent run.  The
    `jobs_loading` flag is set and cleared around each scrape to inform
    API clients that a refresh is in progress.  The jobs_cache is only
    replaced when a scrape completes successfully to ensure that stale
    data are never lost if an error occurs.
    """
    global jobs_loading
    while True:
        try:
            logging.info("Periodic scraper starting full scrape…")
            jobs_loading = True
            run_full_scrape()
        finally:
            jobs_loading = False
        # Sleep for the configured interval before next refresh
        time.sleep(REFRESH_INTERVAL_SEC)


def run_full_scrape() -> None:
    """Background thread function to scrape all configured pages.

    This function aggregates jobs from all FreeJobAlert pages defined in
    api_jobs.  It deduplicates and sorts them by last date, then stores
    the result in the global jobs_cache and marks jobs_loaded = True.
    """
    global jobs_cache, jobs_loaded
    logging.info("Starting full scrape in background thread…")
    # Collect jobs incrementally so we can update the cache as we go.  We
    # maintain a local list and update the global cache after each page
    # scrape, deduplicating and truncating to MAX_JOBS_TO_CACHE.  This
    # allows the API to serve partial results while scraping continues.
    local_jobs: List[Dict[str, Any]] = []
    try:
        # Aggregate jobs from table pages
        table_pages: List[Tuple[str, str]] = [
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
            try:
                page_jobs = scrape_freejobalert_table_page(url, cat)
                local_jobs.extend(page_jobs)
                logging.info("Scraped %d jobs from %s", len(page_jobs), url)
                # Update cache incrementally after each page
                update_cache_snapshot(local_jobs, mark_loaded=False)
            except Exception as e:
                logging.error("Error scraping FreeJobAlert table page %s: %s", url, e)
        # State pages
        state_pages: Dict[str, str] = {
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
            try:
                page_jobs = scrape_freejobalert_table_page(url, state_name, state=state_name)
                local_jobs.extend(page_jobs)
                logging.info("Scraped %d jobs from %s", len(page_jobs), url)
                # Update cache incrementally
                update_cache_snapshot(local_jobs, mark_loaded=False)
            except Exception as e:
                logging.error("Error scraping FreeJobAlert state page %s: %s", url, e)
        # City/location pages
        search_pages: Dict[str, Tuple[str, Optional[str]]] = {
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
            try:
                page_jobs = scrape_freejobalert_search_page(url, category=cat, inferred_state=forced_state)
                local_jobs.extend(page_jobs)
                logging.info("Scraped %d jobs from %s", len(page_jobs), url)
                # Update cache incrementally
                update_cache_snapshot(local_jobs, mark_loaded=False)
            except Exception as e:
                logging.error("Error scraping FreeJobAlert search page %s: %s", url, e)
        # Qualification pages
        qualification_pages: Dict[str, str] = {
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
            try:
                page_jobs = scrape_freejobalert_search_page(url, category=cat)
                local_jobs.extend(page_jobs)
                logging.info("Scraped %d jobs from %s", len(page_jobs), url)
                # Update cache incrementally
                update_cache_snapshot(local_jobs, mark_loaded=False)
            except Exception as e:
                logging.error("Error scraping FreeJobAlert qualification page %s: %s", url, e)
        # Final deduplication and update after all pages have been scraped
        update_cache_snapshot(local_jobs, mark_loaded=True)
        logging.info(
            "Full scrape completed: %d jobs collected (truncated to %d)",
            len(dedupe_and_sort_jobs(local_jobs)),
            min(len(dedupe_and_sort_jobs(local_jobs)), MAX_JOBS_TO_CACHE),
        )
    except Exception as e:
        logging.error("Exception in background scrape: %s", e)



def scrape_freejobalert_all_jobs() -> List[Dict[str, Any]]:
    """Scrape all job postings from the FreeJobAlert government jobs page.

    The page contains multiple categories (UPSC, SSC, Other All India, All India Fellow, etc.).
    Rather than selecting a single section, this function collects every row
    containing a "Get Details" link and extracts the job information from that row.

    Returns a list of job dictionaries with keys: title, board, qualification,
    lastDate, source, and url.
    """
    jobs: List[Dict[str, Any]] = []
    url = "https://www.freejobalert.com/government-jobs/"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch FreeJobAlert page: %s", e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Find all rows that contain a link whose text includes "Get Details"
    for link in soup.find_all("a", string=lambda t: t and "Get Details" in t):
        row = link.find_parent("tr")
        if not row:
            continue
        cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        # Some categories may not provide full set of columns; ensure at least 6 values
        if len(cols) < 6:
            continue
        # Column ordering for most tables: Post Date, Board, Title, Qualification, Advt No, Last Date
        post_date = cols[0]
        board = cols[1]
        title = cols[2]
        qualification = cols[3]
        last_date_str = cols[5] if len(cols) > 5 else ""
        try:
            last_date = datetime.strptime(last_date_str, "%d-%m-%Y").date().isoformat()
        except Exception:
            last_date = ""
        # Construct absolute URL in case the href is relative or truncated
        job_url = link.get("href", "")
        if job_url:
            job_url = requests.compat.urljoin(url, job_url)
        jobs.append(
            {
                "title": title,
                "board": board,
                "qualification": qualification,
                "lastDate": last_date,
                "source": "FreeJobAlert",
                "url": job_url,
            }
        )
    return jobs


def scrape_freejobalert_jk_jobs() -> List[Dict[str, Any]]:
    """Scrape Jammu & Kashmir government job postings from FreeJobAlert.

    The JK government jobs page lists various posts with details similar to the
    general government jobs page.  This function extracts each row that
    contains a "Get Details" link and returns structured job information.
    """
    jobs: List[Dict[str, Any]] = []
    url = "https://www.freejobalert.com/jk-government-jobs/"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch JK government jobs page: %s", e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.find_all("a", string=lambda t: t and "Get Details" in t):
        row = link.find_parent("tr")
        if not row:
            continue
        cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if len(cols) < 6:
            continue
        board = cols[1]
        title = cols[2]
        qualification = cols[3]
        last_date_str = cols[5] if len(cols) > 5 else ""
        try:
            last_date = datetime.strptime(last_date_str, "%d-%m-%Y").date().isoformat()
        except Exception:
            last_date = ""
        # Construct absolute URL in case of relative path
        job_url = link.get("href", "")
        if job_url:
            job_url = requests.compat.urljoin(url, job_url)
        jobs.append(
            {
                "title": title,
                "board": board,
                "qualification": qualification,
                "lastDate": last_date,
                "source": "FreeJobAlert JK",
                "url": job_url,
            }
        )
    return jobs


# New scraping functions for FreeJobAlert latest notifications and state government jobs

def scrape_freejobalert_latest_notifications() -> List[Dict[str, Any]]:
    """Scrape all job postings from FreeJobAlert's latest notifications page.

    The latest notifications page lists jobs across multiple categories (e.g., Banks,
    Finance, UPSC, SSC, etc.) in tabular form. Each row typically contains the
    post date, recruiting organisation, post title, required qualification,
    advertisement number and closing date along with a "Get Details" link.

    This function collects every row containing a "Get Details" link, extracts
    the relevant fields and returns a list of job dictionaries.  The returned
    jobs include a "state" key set to ``None`` because the latest notifications
    page does not associate a state with its listings.
    """
    jobs: List[Dict[str, Any]] = []
    url = "https://www.freejobalert.com/latest-notifications/"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch FreeJobAlert latest notifications: %s", e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Iterate over all tables on the page.  Each table corresponds to a category.
    for table in soup.find_all("table"):
        for link in table.find_all("a", string=lambda t: t and "Get Details" in t):
            row = link.find_parent("tr")
            if not row:
                continue
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            # Expect at least 6 columns: Post Date, Board, Title, Qualification, Advt No, Last Date
            if len(cols) < 6:
                continue
            board = cols[1]
            title = cols[2]
            qualification = cols[3]
            last_date_str = cols[5] if len(cols) > 5 else ""
            try:
                last_date = datetime.strptime(last_date_str, "%d-%m-%Y").date().isoformat()
            except Exception:
                last_date = ""
            # Attempt to parse number of posts from the title (e.g. "XYZ – 30 Posts")
            post_count = None
            m = re.search(r"(\d+[\d,]*)\s*Posts?", title, re.IGNORECASE)
            if m:
                try:
                    post_count = int(m.group(1).replace(",", ""))
                except Exception:
                    post_count = None
            # Construct absolute URL
            job_url = link.get("href", "")
            if job_url:
                job_url = requests.compat.urljoin(url, job_url)
            jobs.append(
                {
                    "title": title,
                    "board": board,
                    "qualification": qualification,
                    "lastDate": last_date,
                    "source": "FreeJobAlert Latest",
                    "url": job_url,
                    "state": None,
                    "postCount": post_count,
                }
            )
    return jobs


def scrape_freejobalert_table_page(url: str, source_name: str, state: str | None = None) -> List[Dict[str, Any]]:
    """Scrape a FreeJobAlert page that presents job listings in tabular form.

    Many FreeJobAlert pages follow the same structure used for the government jobs
    listings: a series of tables where each row contains the post date,
    recruiting organisation (board), post name, qualification, advertisement
    number and closing date.  A "Get Details" link provides the URL for the
    detailed notification.  Examples include the bank jobs page, teaching jobs
    page, engineering jobs page, railway jobs page and police/defence jobs
    page.

    Parameters
    ----------
    url : str
        The URL of the page to scrape.
    source_name : str
        A short identifier describing the origin of these jobs (e.g. "Bank Jobs").
        This string will be prefixed with "FreeJobAlert" when constructing
        the job's source field.
    state : Optional[str]
        If supplied, every job extracted from this page will be tagged with
        the given state.  This is useful for pages dedicated to a single state
        (e.g. https://www.freejobalert.com/ap-government-jobs/).

    Returns
    -------
    List[Dict[str, Any]]
        A list of job dictionaries with at least the following keys:
        title, board, qualification, lastDate, source, url and state.  When
        possible, the number of vacancies is extracted from the title and stored
        under ``postCount``.
    """
    jobs: List[Dict[str, Any]] = []
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch FreeJobAlert table page %s: %s", url, e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Some pages (like state-specific pages) may contain multiple tables separated
    # by headings.  We extract every row with a "Get Details" link.
    for link in soup.find_all("a", string=lambda t: t and "Get Details" in t):
        row = link.find_parent("tr")
        if not row:
            continue
        cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if len(cols) < 6:
            continue
        board = cols[1]
        title = cols[2]
        qualification = cols[3]
        last_date_str = cols[5] if len(cols) > 5 else ""
        try:
            last_date = datetime.strptime(last_date_str, "%d-%m-%Y").date().isoformat()
        except Exception:
            last_date = ""
        # Attempt to parse number of posts from title (e.g. "XYZ – 30 Posts")
        post_count = None
        m = re.search(r"(\d+[\d,]*)\s*Posts?", title, re.IGNORECASE)
        if m:
            try:
                post_count = int(m.group(1).replace(",", ""))
            except Exception:
                post_count = None
        # Build absolute URL from relative href
        job_url = link.get("href", "")
        if job_url:
            job_url = requests.compat.urljoin(url, job_url)
        jobs.append(
            {
                "title": title,
                "board": board,
                "qualification": qualification,
                "lastDate": last_date,
                "source": f"FreeJobAlert {source_name}",
                "url": job_url,
                "state": state,
                "postCount": post_count,
            }
        )
    return jobs


def scrape_freejobalert_search_page(url: str, category: str | None = None, inferred_state: str | None = None) -> List[Dict[str, Any]]:
    """Scrape a FreeJobAlert "search jobs" style page.

    Pages under ``/search-jobs/`` (e.g. jobs in specific cities or jobs by
    qualification) present each job inside a ``div`` with class ``org_tab``.
    Within this container there is a ``span`` with a short descriptor (often the
    recruiting organisation and year) and a ``table`` listing fields such as
    Post Name, Qualification, No. of Vacancy, Location (for city pages),
    Date Added and Last Date to Apply.  The last row contains an "Apply Now"
    link to the detailed notification.

    This function iterates through all ``org_tab`` blocks, extracts the
    relevant fields and returns a list of job dictionaries.  When ``category``
    is provided, it is appended to the job's source for clarity.  If
    ``inferred_state`` is supplied, it overrides any state inferred from the
    location field.

    Returns
    -------
    List[Dict[str, Any]]
        A list of job dictionaries with keys: title, board, qualification,
        lastDate, source, url, state (when known) and postCount (if
        convertible from the vacancy field).
    """
    jobs: List[Dict[str, Any]] = []
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch FreeJobAlert search page %s: %s", url, e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Each job is enclosed in a div.org_tab
    for div in soup.find_all("div", class_="org_tab"):
        # The span text typically contains the recruiting organisation (e.g. "RBI Jobs 2026")
        span = div.find("span")
        board = span.get_text(strip=True) if span else ""
        # Create a mapping from field names to values
        fields: Dict[str, str] = {}
        table = div.find("table")
        if table:
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) == 2:
                    key = tds[0].get_text(strip=True)
                    value = tds[1].get_text(strip=True)
                    fields[key] = value
                # If there's a single cell with a link, it will be the Apply Now row
        # Extract the Apply Now URL
        apply_link = div.find("a", string=lambda t: t and "Apply Now" in t)
        job_url = apply_link["href"] if apply_link and apply_link.has_attr("href") else ""
        # Build absolute URL for apply link
        if job_url:
            job_url = requests.compat.urljoin(url, job_url)
        # Fields of interest
        post_name = fields.get("Post Name") or fields.get("Post Name ") or fields.get("Post Name ")
        qualification = fields.get("Qualification") or fields.get("Qualifications")
        vacancy = fields.get("No. of Vacancy") or fields.get("No. of Vacancies") or fields.get("Vacancies")
        location = fields.get("Location")
        last_date_str = fields.get("Last Date to Apply") or fields.get("Last Date")
        # Compose the title: if board is present, combine with post name; otherwise just post name
        title = post_name
        if board and post_name and board not in post_name:
            title = f"{board} {post_name}".strip()
        # Parse last date
        last_date = ""
        if last_date_str:
            # Convert e.g. "04-Feb-2026" to ISO
            match = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", last_date_str)
            if match:
                day, mon_abbr, year = match.groups()
                try:
                    dt = datetime.strptime(f"{day}-{mon_abbr}-{year}", "%d-%b-%Y")
                    last_date = dt.date().isoformat()
                except Exception:
                    last_date = ""
        # Infer state from location if present and not overridden
        state = inferred_state
        if not state and location and "," in location:
            # Use the part after the last comma as the state name, stripping spaces
            parts = [p.strip() for p in location.split(",")]
            if parts:
                candidate = parts[-1]
                # Normalise by removing words like "District" or "State" if present
                candidate = re.sub(r"\b(\w+ District|District|State)\b", "", candidate, flags=re.IGNORECASE).strip()
                state = candidate or None
        # Parse post count
        post_count = None
        if vacancy:
            m = re.search(r"(\d+[\d,]*)", vacancy)
            if m:
                try:
                    post_count = int(m.group(1).replace(",", ""))
                except Exception:
                    post_count = None
        jobs.append(
            {
                "title": title or board,
                "board": board,
                "qualification": qualification or "",
                "lastDate": last_date,
                "source": f"FreeJobAlert {category}" if category else "FreeJobAlert Search",
                "url": job_url,
                "state": state,
                "postCount": post_count,
                "location": location,
            }
        )
    return jobs


def scrape_freejobalert_state_jobs() -> List[Dict[str, Any]]:
    """Scrape state‑wise government job postings from FreeJobAlert.

    The state government jobs page is organised by state. Each state has an
    anchor (e.g., ``<a name="andaman-and-nicobar"></a>``) followed by an ``<h4>``
    heading with class ``latsec`` containing the state name. Immediately after
    the heading is a table with class ``lattbl`` listing job postings for
    that state.  Each row of the table contains the post date, board,
    post name (which may include the number of vacancies), qualification,
    advertisement number and application closing date.  A "Get Details" link
    provides the URL for the full notification.

    This function iterates through each state section, extracts the jobs and
    attaches the corresponding state name to each job dictionary.
    """
    jobs: List[Dict[str, Any]] = []
    url = "https://www.freejobalert.com/state-government-jobs/"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch FreeJobAlert state jobs: %s", e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Each state section header is an h4 with class "latsec"
    for header in soup.find_all("h4", class_="latsec"):
        state_name = header.get_text(strip=True)
        # The table containing jobs follows the header
        table = header.find_next("table", class_="lattbl")
        if not table:
            continue
        for row in table.find_all("tr"):
            # Each row may contain th/td elements; skip header rows (th)
            link = row.find("a", string=lambda t: t and "Get Details" in t)
            if not link:
                continue
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if len(cols) < 6:
                continue
            board = cols[1]
            title = cols[2]
            qualification = cols[3]
            last_date_str = cols[5] if len(cols) > 5 else ""
            try:
                last_date = datetime.strptime(last_date_str, "%d-%m-%Y").date().isoformat()
            except Exception:
                last_date = ""
            # Parse number of posts from title
            post_count = None
            m = re.search(r"(\d+[\d,]*)\s*Posts?", title, re.IGNORECASE)
            if m:
                try:
                    post_count = int(m.group(1).replace(",", ""))
                except Exception:
                    post_count = None
            # Build absolute URL from relative href
            job_url = link.get("href", "")
            if job_url:
                job_url = requests.compat.urljoin(url, job_url)
            jobs.append(
                {
                    "title": title,
                    "board": board,
                    "qualification": qualification,
                    "lastDate": last_date,
                    "source": f"FreeJobAlert {state_name}",
                    "url": job_url,
                    "state": state_name,
                    "postCount": post_count,
                }
            )
    return jobs


def scrape_indgovtjobs_latest_all_india() -> List[Dict[str, Any]]:
    """Scrape latest all India government jobs from IndGovtJobs.

    Returns a list of jobs with similar structure as scrape_freejobalert_other_all_india().
    """
    jobs: List[Dict[str, Any]] = []
    url = "https://www.indgovtjobs.in/2015/10/Government-Jobs.html"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch IndGovtJobs page: %s", e)
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")
    # Locate the table titled "Latest All India Government Jobs"
    header = soup.find(lambda tag: tag.name in ["h2", "h3"] and "Latest All India" in tag.get_text())
    if not header:
        return jobs
    table = header.find_next("table")
    if not table:
        return jobs
    for row in table.find_all("tr"):
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) >= 5:
            job_title = cols[1]
            board = cols[2]
            qualification = cols[3]
            # The last date may be missing or given as blank; parse if possible
            date_text = cols[4]
            try:
                last_date = datetime.strptime(date_text, "%d-%m-%Y").date().isoformat()
            except Exception:
                last_date = ""
            # Link to details may be present in <a> tag in row
            link = row.find("a", href=True)
            details_url = link["href"] if link else ""
            jobs.append(
                {
                    "title": job_title,
                    "board": board,
                    "qualification": qualification,
                    "lastDate": last_date,
                    "source": "IndGovtJobs",
                    "url": details_url,
                }
            )
    return jobs


def fetch_job_details(job_url: str) -> Dict[str, Any]:
    """Fetch and parse a job details page.

    Attempts to extract rich information such as post name, number of posts,
    salary, qualification, age limit, last date, official website, and
    extended sections like eligibility criteria, desirable skills, experience,
    salary details, and important dates.  Falls back to simple extraction when
    specific patterns are not found.
    """
    details: Dict[str, Any] = {"url": job_url, "html": ""}
    if not job_url:
        return details
    try:
        resp = requests.get(job_url, timeout=15)
    except Exception as e:
        logging.error("Failed to fetch job details from %s: %s", job_url, e)
        return details
    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove scripts and styles
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Extract plain text for fallback
    text = soup.get_text(separator="\n")
    details["html"] = text
    # Preprocess lines for searching key fields
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Helper to find value after a prefix
    def find_value(prefixes: List[str]) -> str:
        for line in lines:
            for p in prefixes:
                if line.lower().startswith(p.lower() + ":"):
                    return line.split(":", 1)[1].strip()
        return ""

    def normalize_key(text_val: str) -> str:
        return re.sub(r"\s+", " ", text_val.strip().lower())

    def coerce_date_value(raw_val: str) -> str:
        match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", raw_val)
        if match:
            dd, mm, yyyy = match.groups()
            try:
                dt = datetime(int(yyyy), int(mm), int(dd))
                return dt.date().isoformat()
            except Exception:
                return raw_val
        return raw_val

    def parse_table_kv() -> Dict[str, str]:
        table_kv: Dict[str, str] = {}
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                if len(cells) < 2:
                    continue
                key = normalize_key(cells[0])
                val = " ".join([c for c in cells[1:] if c])
                if key and val and key not in table_kv:
                    table_kv[key] = val
        return table_kv

    def parse_important_dates_table() -> List[Dict[str, str]]:
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_cells = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if not header_cells:
                continue
            if "event" in " ".join(header_cells) and "date" in " ".join(header_cells):
                items: List[Dict[str, str]] = []
                for row in rows[1:]:
                    cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                    if len(cells) >= 2:
                        items.append({"event": cells[0], "date": cells[1]})
                if items:
                    return items
        return []
    # Table-based key/value extraction for FreeJobAlert article pages
    table_kv = parse_table_kv()
    key_map = {
        "company name": "companyName",
        "name of company": "companyName",
        "organization": "companyName",
        "organisation": "companyName",
        "post name": "postName",
        "post names": "postName",
        "name of post": "postName",
        "no of posts": "noOfPosts",
        "no. of posts": "noOfPosts",
        "number of posts": "noOfPosts",
        "advt no": "advtNo",
        "advt. no": "advtNo",
        "advertisement no": "advtNo",
        "salary": "salary",
        "pay scale": "salary",
        "qualification": "qualification",
        "age limit": "ageLimit",
        "start date for apply": "startDate",
        "start date": "startDate",
        "last date for apply": "lastDate",
        "last date": "lastDate",
        "official website": "officialWebsite",
    }
    for raw_key, val in table_kv.items():
        mapped = key_map.get(raw_key)
        if not mapped or mapped in details:
            continue
        if mapped == "ageLimit":
            details[mapped] = [val]
        elif mapped == "lastDate":
            details[mapped] = coerce_date_value(val)
        else:
            details[mapped] = val

    important_dates_table = parse_important_dates_table()
    if important_dates_table:
        details["importantDatesTable"] = important_dates_table

    # Post Name / Title
    post_name = find_value(["post name", "post names", "post", "name of post"])
    if post_name:
        details["postName"] = post_name
    # Number of Posts
    no_posts = find_value(["no of posts", "no. of posts", "number of posts", "no of vacancy", "vacancies"])
    if no_posts:
        details["noOfPosts"] = no_posts
    # Salary / Pay
    salary = find_value(["salary", "pay scale", "stipend"])
    if salary:
        details["salary"] = salary
        details["salaryDetails"] = [salary]
    # Qualification
    qualification = find_value(["qualification", "educational qualification", "essential qualification"])
    if qualification:
        details["qualification"] = qualification
    # Age limit (single line value)
    age_limit_val = find_value(["age limit", "age", "age as on"])
    if age_limit_val:
        # Could be a range; split by comma
        details["ageLimit"] = [age_limit_val]
    # Last date (if present in details page; fallback is from listing)
    last_date = find_value(["last date", "last date for online application", "last date to apply"])
    if last_date:
        details["lastDate"] = coerce_date_value(last_date)
    # Official Website
    # Look for anchor text containing 'official website'
    for a in soup.find_all("a", href=True):
        if "official" in a.get_text(strip=True).lower() and "website" in a.get_text(strip=True).lower():
            details["officialWebsite"] = a['href']
            break
    # Extract sections by heading
    def extract_section_by_heading(heading_keywords: List[str]) -> List[str]:
        # Find first heading matching any keyword
        header = soup.find(lambda tag: tag.name in ["h2", "h3", "h4", "h5"] and any(k.lower() in tag.get_text(strip=True).lower() for k in heading_keywords))
        if not header:
            return []
        section_lines: List[str] = []
        for sibling in header.find_all_next():
            if sibling.name in ["h2", "h3", "h4", "h5"]:
                break
            if sibling.name in ["li", "p"]:
                text = sibling.get_text(strip=True)
                if text:
                    section_lines.append(text)
        return section_lines
    def extract_important_links_strict() -> List[Dict[str, str]]:
        def normalize_url(url_val: str) -> str:
            if not url_val:
                return ""
            if url_val.startswith("//"):
                return f"https:{url_val}"
            if url_val.startswith("http://") or url_val.startswith("https://"):
                return url_val
            return f"https://{url_val}"

        def domain_from_url(url_val: str) -> str:
            cleaned = re.sub(r"^https?://", "", url_val)
            return cleaned.split("/")[0]

        def find_official_sites() -> List[str]:
            urls: List[str] = []
            for a in soup.find_all("a", href=True):
                if "official" in a.get_text(strip=True).lower() and "website" in a.get_text(strip=True).lower():
                    url_val = normalize_url(a["href"])
                    if url_val and url_val not in urls:
                        urls.append(url_val)
            for a in soup.find_all("a", href=True):
                text_val = a.get_text(" ", strip=True)
                if text_val and re.search(r"\.gov\.in\b", text_val, re.IGNORECASE):
                    url_val = normalize_url(a["href"])
                    if url_val and url_val not in urls:
                        urls.append(url_val)
            for match in re.findall(r"\b([a-z0-9.-]+\.(?:gov\.in|nic\.in|edu\.in|org|in))\b", text, re.IGNORECASE):
                url_val = normalize_url(match)
                if url_val and url_val not in urls:
                    urls.append(url_val)
            return urls[:2]

        def find_notifications() -> List[str]:
            candidates: List[str] = []
            # Primary target: <li> containing "Official Notification PDF"
            for li in soup.find_all("li"):
                li_text = li.get_text(" ", strip=True).lower()
                if "official notification pdf" in li_text:
                    a = li.find("a", href=True)
                    if a:
                        href = normalize_url(a["href"])
                        if href and href not in candidates:
                            candidates.append(href)
            # Secondary target: pdf links with nearby notification text
            if len(candidates) < 2:
                for a in soup.find_all("a", href=True):
                    href = normalize_url(a["href"])
                    if not href.lower().endswith(".pdf"):
                        continue
                    if href in candidates:
                        continue
                    container = a.find_parent(["li", "p", "div"]) or a.parent
                    context_text = (container.get_text(" ", strip=True).lower() if container else "")
                    if any(k in context_text for k in [
                        "official notification",
                        "notification pdf",
                        "notification",
                        "advertisement",
                        "detailed notification",
                        "download",
                    ]):
                        candidates.append(href)
                    if len(candidates) >= 2:
                        break
            return candidates

        official_sites = find_official_sites()
        notifications = find_notifications()
        notifications = notifications[:2]

        links: List[Dict[str, str]] = []
        for site in official_sites:
            links.append(
                {
                    "type": "officialWebsite",
                    "label": "Official Website:",
                    "display": domain_from_url(site),
                    "url": site,
                }
            )
        for href in notifications:
            links.append(
                {
                    "type": "officialNotification",
                    "label": "Official Notification PDF :",
                    "display": "CLICK HERE",
                    "url": href,
                }
            )
        return links
    # Eligibility (essential qualifications)
    elig = extract_section_by_heading(["Eligibility", "Essential Qualification", "Essential Qualifications"])
    if elig:
        details["eligibility"] = elig
    # Desirable skills
    desirable = extract_section_by_heading(["Desirable Skills", "Desired Skills", "Desirable Qualification"])
    if desirable:
        details["desirableSkills"] = desirable
    # Experience
    exp = extract_section_by_heading(["Experience", "Work Experience"])
    if exp:
        details["experience"] = exp
    # Salary Details / Stipend
    sal_details = extract_section_by_heading(["Salary", "Stipend", "Pay"])
    if sal_details:
        details["salaryDetails"] = sal_details
        # If salary was not set earlier, set from first line
        if "salary" not in details:
            details["salary"] = sal_details[0]
    # Important Dates
    important = extract_section_by_heading(["Important Dates", "Important Date", "Important dates"])
    if important:
        details["importantDates"] = important

    selection = extract_section_by_heading(["Selection Process", "Selection"])
    if selection:
        details["selectionProcess"] = selection

    general = extract_section_by_heading(["General Information", "General Instructions", "Instructions"])
    if general:
        details["generalInstructions"] = general

    how_to_apply = extract_section_by_heading(["How to Apply", "How to apply"])
    if how_to_apply:
        details["howToApply"] = how_to_apply

    important_links = extract_important_links_strict()
    details["officialWebsites"] = [link.get("url") for link in important_links if link.get("type") == "officialWebsite" and link.get("url")]
    if not any(link.get("type") == "officialNotification" for link in important_links):
        details["officialNotificationStatus"] = "Official Notification PDF : N/A"
    details["importantLinks"] = important_links

    # Age limit section captured by heading (e.g., "Age Limit (as on ...)")
    if "ageLimit" not in details:
        age_sec = extract_section_by_heading(["Age Limit"])
        if age_sec:
            # Flatten lines into a single entry or list
            # Remove bullet symbols if present
            cleaned = []
            for line in age_sec:
                stripped = line.strip()
                if stripped:
                    cleaned.append(stripped)
            if cleaned:
                details["ageLimit"] = cleaned

    return details


@app.route("/api/jobs")
def api_jobs():
    """Aggregate job postings from various FreeJobAlert pages with pagination support.

    The API returns a slice of the full job list based on optional query parameters
    ``offset`` and ``limit``.  If unspecified, ``offset`` defaults to 0 and
    ``limit`` defaults to 50.  The response JSON has two keys:

        * ``jobs`` – the list of job objects in the requested window
        * ``next_offset`` – the next offset to request, or ``null`` if there
          are no additional jobs

    This allows the front‑end to dynamically load more jobs by making
    subsequent requests with the returned ``next_offset`` value.
    """
    # Parse offset and limit from query parameters
    try:
        offset = int(request.args.get('offset', 0))
        if offset < 0:
            offset = 0
    except Exception:
        offset = 0
    try:
        limit = int(request.args.get('limit', 50))
        # upper bound aligned with cache size to allow full cache reloads
        if limit <= 0 or limit > MAX_JOBS_TO_CACHE:
            limit = 50
    except Exception:
        limit = 50

    # Start the periodic scraping thread on the first request if not already started.
    # This ensures the cache is refreshed every REFRESH_INTERVAL_SEC seconds without
    # blocking API responses.  A quick scrape of the government jobs page is
    # performed only if the cache is currently empty to provide initial data.
    global jobs_loaded, jobs_cache
    ensure_scrape_thread_started()
    # Perform a quick scrape of the government jobs page if cache is empty
    if not jobs_cache:
        try:
            quick_jobs = scrape_freejobalert_table_page(
                "https://www.freejobalert.com/government-jobs/", "Govt Jobs"
            )
        except Exception as e:
            logging.error("Quick scrape failed: %s", e)
            quick_jobs = []
        update_cache_snapshot(quick_jobs, mark_loaded=False)
        logging.info("Quick scrape seeded %d jobs", len(quick_jobs))

    # Acquire current job list snapshot
    with scrape_lock:
        current_jobs = list(jobs_cache)
        loaded = jobs_loaded
    # Deduplicate and sort on each request to avoid returning stale duplicates
    deduped = dedupe_and_sort_jobs(current_jobs)
    total = len(deduped)
    # Compute slice boundaries
    start = offset
    end = min(offset + limit, total)
    page_jobs = deduped[start:end]
    # Determine next_offset: if more data available in deduped list
    if end < total:
        next_offset = end
    else:
        next_offset = None
    # Determine loading state: true if the first full scrape has not completed or a refresh is in progress.
    loading_flag = (not loaded) or jobs_loading
    return jsonify({
        "jobs": page_jobs,
        "next_offset": next_offset,
        "loading": loading_flag
    })


@app.route("/api/job_details")
def api_job_details():
    job_url = request.args.get("url")
    if not job_url:
        return abort(400, description="Missing 'url' query parameter")
    details = fetch_job_details(job_url)
    return jsonify(details)


# Always register the root path handler so that the index.html file is served
# regardless of how the Flask app is launched.  When running via flask or
# through WSGI, this ensures the front‑end loads correctly.
@app.route('/')
def root_index():
    """Serve the main index.html for the front‑end."""
    return app.send_static_file('index.html')

if __name__ == "__main__":
    # Run the server on localhost port 5000.  The root route is already
    # registered above.
    app.run(host="0.0.0.0", port=5000)
