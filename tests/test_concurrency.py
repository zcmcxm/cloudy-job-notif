"""runner.scrape_all: concurrent, capped, order-preserving, and failure-isolated.

Fake scrapers `await asyncio.sleep(...)` to stand in for network time, and count how many
are in flight at once. No real HTTP.
"""

import asyncio
import time

import pytest
from conftest import make_job

from job_alert import runner
from job_alert.models import AppConfig, CompanyConfig
from job_alert.store import LocalJsonStore


def companies(n, type_="fake"):
    return [CompanyConfig(id=f"c{i}", name=f"C{i}", type=type_) for i in range(n)]


class Tracker:
    """A fake adapter that records peak concurrency."""

    def __init__(self, delay=0.05, delays=None):
        self.delay, self.delays = delay, delays or {}
        self.in_flight = self.peak = 0

    async def __call__(self, company, client):
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(company.id, self.delay))
            return [make_job("1", company_id=company.id)]
        finally:
            self.in_flight -= 1


@pytest.fixture
def adapter(monkeypatch):
    tracker = Tracker()
    monkeypatch.setattr(runner, "get_scraper", lambda type_: tracker)
    return tracker


def scrape_all(cs, limit=runner.MAX_CONCURRENCY):
    return asyncio.run(runner.scrape_all(cs, client=None, limit=limit))


def test_scrapes_overlap(adapter):
    start = time.perf_counter()
    outcomes = scrape_all(companies(8))
    elapsed = time.perf_counter() - start

    assert adapter.peak == 8
    assert elapsed < 8 * adapter.delay / 2, f"took {elapsed:.2f}s: looks sequential"
    assert [o[0].company_id for o in outcomes] == [f"c{i}" for i in range(8)]


def test_concurrency_is_capped(adapter):
    scrape_all(companies(20), limit=3)
    assert adapter.peak == 3


def test_default_cap_is_max_concurrency(adapter):
    scrape_all(companies(20))
    assert adapter.peak == runner.MAX_CONCURRENCY


def test_results_keep_config_order_not_finish_order(adapter):
    adapter.delays = {"c0": 0.06, "c1": 0.04, "c2": 0.02, "c3": 0.0}  # finish in reverse
    outcomes = scrape_all(companies(4))
    assert [o[0].company_id for o in outcomes] == ["c0", "c1", "c2", "c3"]


def test_one_failure_does_not_cancel_the_others(monkeypatch):
    finished = []

    async def flaky(company, client):
        await asyncio.sleep(0.01)
        if company.id == "c1":
            raise RuntimeError("site down")
        await asyncio.sleep(0.02)  # still running when c1 fails
        finished.append(company.id)
        return []

    monkeypatch.setattr(runner, "get_scraper", lambda type_: flaky)
    outcomes = scrape_all(companies(3))

    assert isinstance(outcomes[1], RuntimeError) and str(outcomes[1]) == "site down"
    assert outcomes[0] == [] and outcomes[2] == []
    assert sorted(finished) == ["c0", "c2"]


def test_unknown_scraper_type_is_that_companys_outcome():
    """get_scraper raises ValueError for an unknown `type:`; it must not escape scrape_all."""
    [outcome] = scrape_all(companies(1, type_="myspace"))
    assert isinstance(outcome, ValueError) and "Unknown scraper type" in str(outcome)


def test_failed_company_shows_up_as_error_in_the_report(monkeypatch, tmp_path):
    async def broken(company, client):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "get_scraper", lambda type_: broken)
    report = asyncio.run(runner.run(AppConfig(companies=companies(1)), LocalJsonStore(tmp_path / "s.json"), client=None))
    assert report.results[0].error == "RuntimeError: boom"
