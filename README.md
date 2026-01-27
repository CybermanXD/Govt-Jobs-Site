# Govt Jobs Site

A fast, searchable portal for government job listings with clean filters and detail pages.

## Live Site

Access the application here:

- https://govt-jobs-site.onrender.com/

## Features

- Browse up-to-date government job listings
- Quick search and filtering for roles, departments, and locations
- Dedicated detail pages for each listing
- Lightweight frontend for fast load times

## Tech Stack

- Frontend: HTML, CSS, JavaScript
- Backend: Python (Flask)

## Local Development

1. Start the server.
2. Open the app in your browser.

> Note: If you already run the server in your environment, reuse that command and port.

## Job Details Snapshot (Supabase)

The frontend reads job detail payloads from a Supabase JSON file and falls back to
`/api/job_details` when a detail entry is missing. Use the generator script to
build and optionally upload the details snapshot:

```bash
python scripts/build_job_details.py
```

### Environment variables

- `JOBS_LIST_URL` (optional): override jobs list URL
- `DETAILS_LIMIT` (optional): limit number of job details fetched
- `SUPABASE_UPLOAD` (optional): set to `1` to upload to Supabase
- `SUPABASE_URL` (required for upload): Supabase project URL
- `SUPABASE_SERVICE_KEY` (required for upload): Supabase service role key
- `SUPABASE_BUCKET` (optional): bucket name, defaults to `jobs-info`
- `SUPABASE_OBJECT_PATH` (optional): object path, defaults to `jobsDetails.json`

## Project Structure

- `server.py` — backend API and server
- `website/` — frontend assets (HTML, CSS, JS)
- `jobs_cache.json` — cached job data

## Contributing

Contributions are welcome. Please open an issue or submit a pull request with a clear description of the change.

## License

MIT
