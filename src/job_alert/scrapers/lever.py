"""Lever public postings API.

Endpoint: GET https://api.lever.co/v0/postings/{token}?mode=json
Response: a JSON *list* of postings. Look at tests/fixtures/lever_postings.json for the shape.

Field mapping to Job:
  job_id     <- "id"
  title      <- "text"
  location   <- "categories" -> "location"   (may be missing)
  department <- "categories" -> "team"       (may be missing)
  url        <- "hostedUrl"

Run `pytest tests/test_scrapers.py -k lever` to check your implementation.
"""

from __future__ import annotations

import httpx

from job_alert.models import CompanyConfig, Job
from job_alert.scrapers.base import require_token

API = "https://api.lever.co/v0/postings/{token}"


async def fetch(company: CompanyConfig, client: httpx.AsyncClient) -> list[Job]:
    resp = await client.get(API.format(token=require_token(company)), params={"mode": "json"})
    resp.raise_for_status()
    return [
        Job(
            company_id=company.id,
            job_id=str(item["id"]),
            title=item.get("text", "").strip(),
            location=(item.get("categories") or {}).get("location", ""),
            url=item.get("hostedUrl", ""),
            department=(item.get("categories") or {}).get("team", ""),
        )
        for item in resp.json()
    ]
