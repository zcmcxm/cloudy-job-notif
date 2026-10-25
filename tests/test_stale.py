"""Stale roles: relevant roles open > matching.stale_after_days are hidden, never re-announced."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from conftest import make_job
from test_notifier import _report

from job_alert import runner
from job_alert.models import AppConfig, CompanyConfig, MatchedJob, MatchingRules, MatchResult
from job_alert.notifier import render_html, render_text
from job_alert.store import LocalJsonStore

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
RULES = MatchingRules(include_title=["python"], stale_after_days=45)


def matched(open_since):
    return MatchedJob(job=make_job("1", "Python Dev"), match=MatchResult(relevant=True), open_since=open_since)


# --- TODO(stale-1) is_stale -------------------------------------------------------

@pytest.mark.parametrize("age, stale", [
    (timedelta(0), False),
    (timedelta(days=45), False),                     # exactly 45 days: not yet
    (timedelta(days=45, seconds=1), True),
    (timedelta(days=200), True),
])
def test_is_stale_boundary(age, stale):
    assert runner.is_stale(matched(T0), RULES, T0 + age) is stale


def test_disabled_when_not_configured():
    rules = MatchingRules(include_title=["python"])  # stale_after_days defaults to None
    assert not runner.is_stale(matched(T0), rules, T0 + timedelta(days=1000))


def test_unknown_open_since_is_not_stale():
    assert not runner.is_stale(matched(None), RULES, T0 + timedelta(days=1000))


def test_config_rejects_nonsense():
    with pytest.raises(ValueError):
        MatchingRules(stale_after_days=0)


# --- TODO(stale-2) runner ---------------------------------------------------------

@pytest.fixture
def setup(tmp_path, monkeypatch):
    scraped = {"jobs": []}

    async def fake_scraper(company, client):
        return scraped["jobs"]

    monkeypatch.setattr(runner, "get_scraper", lambda type_: fake_scraper)
    config = AppConfig(companies=[CompanyConfig(id="acme", name="Acme", type="fake")], matching=RULES)
    return scraped, config, tmp_path / "store.json"


def run(config, path, now):
    store = LocalJsonStore(path)
    report = asyncio.run(runner.run(config, store, client=None, now=now))
    store.save()
    return report


def test_long_open_relevant_role_is_hidden_but_still_open(setup):
    scraped, config, path = setup
    scraped["jobs"] = [make_job("old", "Python Dev")]
    run(config, path, T0)

    scraped["jobs"] = [make_job("old", "Python Dev"), make_job("fresh", "Python Lead")]
    report = run(config, path, T0 + timedelta(days=46))
    result = report.results[0]

    assert [m.job.job_id for m in result.relevant_open] == ["fresh"]
    assert result.stale_relevant == 1
    assert result.total_open == 2  # stale is still open
    assert report.stale_after_days == 45 and report.stale_relevant == 1
    assert {j.job_id for j in LocalJsonStore(path).get_open_jobs("acme")} == {"old", "fresh"}


def test_stale_role_is_never_re_announced_as_new(setup):
    scraped, config, path = setup
    scraped["jobs"] = [make_job("old", "Python Dev")]
    run(config, path, T0)
    run(config, path, T0 + timedelta(days=46))

    result = run(config, path, T0 + timedelta(days=47)).results[0]
    assert result.new == [] and result.stale_relevant == 1


def test_role_within_threshold_is_listed(setup):
    scraped, config, path = setup
    scraped["jobs"] = [make_job("1", "Python Dev")]
    run(config, path, T0)

    result = run(config, path, T0 + timedelta(days=45)).results[0]
    assert [m.job.job_id for m in result.relevant_open] == ["1"] and result.stale_relevant == 0


# --- digest (provided) ------------------------------------------------------------

def test_digest_mentions_hidden_stale_roles():
    report = _report()
    report.stale_after_days = 45
    report.results[0].stale_relevant = 3
    assert "3 relevant roles open more than 45 days hidden as stale" in render_html(report)
    assert "(3 relevant open more than 45 days hidden as stale)" in render_text(report)


def test_digest_is_quiet_when_nothing_is_stale():
    assert "stale" not in render_html(_report()) and "stale" not in render_text(_report())
