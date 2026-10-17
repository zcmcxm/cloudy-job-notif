"""End-to-end run against a fake scraper + temp store. Passes once diff.py and matcher.py are done."""

from datetime import datetime, timezone

import pytest
from conftest import make_job

from job_alert import runner
from job_alert.models import AppConfig, CompanyConfig, MatchingRules
from job_alert.store import LocalJsonStore

T1 = datetime(2026, 10, 5, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    scraped = {"jobs": []}
    monkeypatch.setattr(runner, "get_scraper", lambda type_: lambda company, client: scraped["jobs"])
    config = AppConfig(
        companies=[CompanyConfig(id="acme", name="Acme", type="fake")],
        matching=MatchingRules(include_title=["python"]),
    )
    return scraped, config, tmp_path / "store.json"


def test_baseline_then_diff(setup):
    scraped, config, path = setup

    scraped["jobs"] = [make_job("1", "Python Dev"), make_job("2", "Designer")]
    store = LocalJsonStore(path)
    first = runner.run(config, store, client=None, now=T1).results[0]
    store.save()
    assert first.baseline and len(first.new) == 2

    scraped["jobs"] = [make_job("2", "Designer"), make_job("3", "Python Lead")]
    store = LocalJsonStore(path)
    second = runner.run(config, store, client=None, now=T2).results[0]
    assert not second.baseline
    assert [m.job.job_id for m in second.new] == ["3"]
    assert second.new[0].match.relevant
    assert [j.job_id for j in second.closed] == ["1"]
    assert second.total_open == 2


def test_empty_scrape_does_not_mass_close(setup):
    scraped, config, path = setup
    scraped["jobs"] = [make_job("1")]
    store = LocalJsonStore(path)
    runner.run(config, store, client=None, now=T1)

    scraped["jobs"] = []
    result = runner.run(config, store, client=None, now=T2).results[0]
    assert result.error and "skipped diff" in result.error
    assert len(store.get_open_jobs("acme")) == 1


def test_digest_only_lists_roles_in_my_locations(setup):
    scraped, config, path = setup
    config.matching = MatchingRules(include_title=["python"], include_location=["singapore"])
    store = LocalJsonStore(path)

    scraped["jobs"] = [make_job("1", "Python Dev", "Singapore"), make_job("2", "Python Dev", "New York")]
    first = runner.run(config, store, client=None, now=T1).results[0]
    assert [m.job.job_id for m in first.new] == ["1"]
    assert first.total_open == 1 and first.hidden_new == 1

    scraped["jobs"] = [
        make_job("3", "Designer", "London, Singapore"),  # in location, irrelevant title: still listed
        make_job("4", "Python Lead", "Tokyo"),
        make_job("5", "Analyst", ""),  # unknown location: listed
    ]
    second = runner.run(config, store, client=None, now=T2).results[0]
    assert [m.job.job_id for m in second.new] == ["3", "5"]
    assert [m.match.relevant for m in second.new] == [False, False]
    assert second.hidden_new == 1
    assert [j.job_id for j in second.closed] == ["1"]  # job 2 closed too, but it's in New York
    assert second.total_open == 2

    # Every job is still stored, so diffs stay correct for all locations.
    assert {j.job_id for j in store.get_open_jobs("acme")} == {"3", "4", "5"}


def test_last_local_role_closing_is_not_flagged_as_broken_scrape(setup):
    scraped, config, path = setup
    config.matching = MatchingRules(include_location=["singapore"])
    store = LocalJsonStore(path)

    scraped["jobs"] = [make_job("1", location="Singapore"), make_job("2", location="London")]
    runner.run(config, store, client=None, now=T1)

    scraped["jobs"] = [make_job("2", location="London")]
    result = runner.run(config, store, client=None, now=T2).results[0]
    assert result.error is None
    assert [j.job_id for j in result.closed] == ["1"] and result.total_open == 0


def test_relevant_open_includes_still_open_roles_and_flags_new(setup):
    scraped, config, path = setup
    config.matching = MatchingRules(include_title=["python"], include_location=["singapore"])
    store = LocalJsonStore(path)

    scraped["jobs"] = [make_job("1", "Python Dev", "Singapore"), make_job("2", "Designer", "Singapore")]
    runner.run(config, store, client=None, now=T1)

    scraped["jobs"] = [
        make_job("1", "Python Dev", "Singapore"),   # still open, relevant
        make_job("2", "Designer", "Singapore"),     # still open, not relevant
        make_job("3", "Python Lead", "Singapore"),  # new, relevant
        make_job("4", "Python Lead", "Tokyo"),      # new, relevant title, wrong location
    ]
    result = runner.run(config, store, client=None, now=T2).results[0]
    assert [(m.job.job_id, m.is_new) for m in result.relevant_open] == [("3", True), ("1", False)]
    assert [m.open_since for m in result.relevant_open] == [T2, T1]  # new: this run; still open: first run
    assert [m.job.job_id for m in result.new] == ["3"]
    assert result.total_open == 3 and result.hidden_new == 1
