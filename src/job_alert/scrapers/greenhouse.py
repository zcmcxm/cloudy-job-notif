"""Greenhouse public job board API (worked example — use it as a template for lever.py).

Docs: https://developers.greenhouse.io/job-board.html
"""

from __future__ import annotations

import httpx

from job_alert.models import CompanyConfig, Job
from job_alert.scrapers.base import require_token

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def fetch(company: CompanyConfig, client: httpx.Client) -> list[Job]:
    resp = client.get(API.format(token=require_token(company)))
    resp.raise_for_status()
    return [
        Job(
            company_id=company.id,
            job_id=str(item["id"]),
            title=item["title"].strip(),
            location=(item.get("location") or {}).get("name", ""),
            url=item["absolute_url"],
        )
        for item in resp.json()["jobs"]
    ]
