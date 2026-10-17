"""Eightfold AI careers sites (e.g. career.mlp.com, <company>.eightfold.ai).

How to spot one: the careers URL looks like `/careers?...&domain=<something>&pid=...`
and the page source mentions "eightfold".

Config:
  - id: mlp
    name: Millennium
    type: eightfold
    url: https://career.mlp.com          # scheme + host of the careers site
    options:
      domain: mlp.com                    # the `domain=` query param from the careers URL
      location: Singapore                # optional server-side filter

Endpoint: GET {url}/api/apply/v2/jobs?domain=<domain>&start=<offset>[&location=<location>]
Response: {"count": <total matching jobs>, "positions": [...]}

The server returns at most 10 positions per page and ignores any page-size param,
so we page by offset until we have `count` jobs or a page comes back empty.
"""

from __future__ import annotations

from typing import Any

import httpx

from job_alert.models import CompanyConfig, Job
from job_alert.scrapers.base import require_option, require_url

API = "{base}/api/apply/v2/jobs"
MAX_PAGES = 50


def fetch(company: CompanyConfig, client: httpx.Client) -> list[Job]:
    endpoint = API.format(base=require_url(company))
    params = {"domain": require_option(company, "domain")}
    if location := company.options.get("location"):
        params["location"] = location

    jobs: list[Job] = []
    for _ in range(MAX_PAGES):
        resp = client.get(endpoint, params={**params, "start": len(jobs)})
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions") or []
        jobs.extend(_to_job(company, item) for item in positions)
        if not positions or len(jobs) >= data.get("count", 0):
            return jobs

    # A partial list would make the runner think the missing jobs closed,
    # then re-announce them as new on the next run.
    raise RuntimeError(f"{company.id}: more than {MAX_PAGES} pages of jobs; refusing to return a partial list")


def _to_job(company: CompanyConfig, item: dict[str, Any]) -> Job:
    return Job(
        company_id=company.id,
        job_id=str(item["id"]),
        title=item["name"].strip(),
        location=item.get("location") or "",
        department=item.get("department") or "",
        url=item["canonicalPositionUrl"],
    )
