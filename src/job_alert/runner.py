"""One full run: scrape every company, diff, match, persist. Shared by the CLI and the Lambda.

Two phases:
  1. scrape_all: fetch every company's jobs concurrently (network-bound, ~all of the run time)
  2. _run_company: diff/match/store one company at a time (fast, and the stores are not
     built for concurrent use)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone

import httpx

from job_alert.diff import compute_diff, is_suspicious_empty
from job_alert.matcher import in_my_locations, match
from job_alert.models import AppConfig, CompanyConfig, CompanyResult, Job, MatchedJob, RunReport
from job_alert.scrapers import get_scraper
from job_alert.store import Store

log = logging.getLogger(__name__)

MAX_CONCURRENCY = 8  # requests in flight at once: fast, but polite to shared hosts like Greenhouse


async def run(config: AppConfig, store: Store, client: httpx.AsyncClient, now: datetime | None = None) -> RunReport:
    now = now or datetime.now(timezone.utc)
    scraped = await scrape_all(config.companies, client)
    results = [_run_company(c, outcome, config, store, now) for c, outcome in zip(config.companies, scraped)]
    return RunReport(started_at=now, results=results)


async def scrape_all(
    companies: Sequence[CompanyConfig], client: httpx.AsyncClient, limit: int = MAX_CONCURRENCY
) -> list[list[Job] | Exception]:
    """Scrape every company concurrently, at most `limit` at a time.

    Returns one outcome per company, in the same order as `companies`: the job list, or the
    exception that company's scrape raised. One broken site must not sink the whole run.
    """
    async def scrape_one(company: CompanyConfig, sem: asyncio.Semaphore) -> list[Job] | Exception:
        """Scrape one company, returning the job list or the exception raised."""
        async with sem:
            try:
                scraper = get_scraper(company.type)
            except Exception as e:
                return e
            try:
                return await scraper(company, client)
            except Exception as e:
                return e
    sem = asyncio.Semaphore(limit)
    return await asyncio.gather(*(scrape_one(c, sem) for c in companies))


def _run_company(
    company: CompanyConfig, outcome: list[Job] | Exception, config: AppConfig, store: Store, now: datetime
) -> CompanyResult:
    if isinstance(outcome, Exception):
        log.error("scrape failed for %s", company.id, exc_info=outcome)
        return CompanyResult(company=company, error=f"{type(outcome).__name__}: {outcome}")
    current = outcome

    rules = config.matching
    baseline = not store.has_company(company.id)
    stored_open = store.get_open_jobs(company.id)

    if is_suspicious_empty(current, stored_open):
        return CompanyResult(
            company=company,
            total_open=sum(in_my_locations(j, rules) for j in stored_open),
            error=f"scrape returned 0 jobs but {len(stored_open)} were open last run; skipped diff",
        )

    # Store every job so diffs stay correct; only the digest is limited to your locations.
    diff = compute_diff(current, stored_open)
    store.record_seen(diff.new + diff.still_open, now)
    store.mark_closed(diff.closed, now)
    store.ensure_company(company.id)

    new_ids = {j.job_id for j in diff.new}
    first_seen = {j.job_id: j.first_seen for j in stored_open}
    open_here = [
        MatchedJob(
            job=j,
            match=match(j, rules),
            is_new=j.job_id in new_ids,
            open_since=first_seen.get(j.job_id, now),
        )
        for j in diff.new + diff.still_open
        if in_my_locations(j, rules)
    ]
    new_here = [m for m in open_here if m.is_new]
    return CompanyResult(
        company=company,
        total_open=len(open_here),
        new=new_here,
        relevant_open=[m for m in open_here if m.match.relevant],
        closed=[j for j in diff.closed if in_my_locations(j, rules)],
        hidden_new=len(diff.new) - len(new_here),
        baseline=baseline,
    )
