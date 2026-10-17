"""One full run: scrape every company, diff, match, persist. Shared by the CLI and the Lambda."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from job_alert.diff import compute_diff, is_suspicious_empty
from job_alert.matcher import in_my_locations, match
from job_alert.models import AppConfig, CompanyConfig, CompanyResult, MatchedJob, RunReport
from job_alert.scrapers import get_scraper
from job_alert.store import Store

log = logging.getLogger(__name__)


def run(config: AppConfig, store: Store, client: httpx.Client, now: datetime | None = None) -> RunReport:
    now = now or datetime.now(timezone.utc)
    results = [_run_company(c, config, store, client, now) for c in config.companies]
    return RunReport(started_at=now, results=results)


def _run_company(
    company: CompanyConfig, config: AppConfig, store: Store, client: httpx.Client, now: datetime
) -> CompanyResult:
    try:
        current = get_scraper(company.type)(company, client)
    except Exception as e:  # one broken site must not sink the whole run
        log.exception("scrape failed for %s", company.id)
        return CompanyResult(company=company, error=f"{type(e).__name__}: {e}")

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
