import pytest
from conftest import make_job

from job_alert.matcher import in_my_locations, match
from job_alert.models import MatchingRules

RULES = MatchingRules(
    include_title=["python", "backend"],
    exclude_title=["intern"],
    include_location=["remote", "london"],
)


def test_title_and_location_match():
    r = match(make_job("1", "Senior Python Developer", "Remote - EU"), RULES)
    assert r.relevant is True
    assert r.reason == "title: python; location: remote"


def test_case_insensitive_and_first_keyword_wins():
    r = match(make_job("1", "BACKEND engineer (python)", "LONDON"), RULES)
    assert r.relevant is True
    assert r.reason == "title: python; location: london"


def test_excluded_title():
    r = match(make_job("1", "Python Intern", "London"), RULES)
    assert r.relevant is False
    assert r.reason == "excluded: intern"


def test_no_title_match():
    r = match(make_job("1", "Product Designer", "London"), RULES)
    assert r.relevant is False
    assert r.reason == "no title match"


def test_no_location_match():
    r = match(make_job("1", "Python Developer", "Berlin"), RULES)
    assert r.relevant is False
    assert r.reason == "no location match"


@pytest.mark.parametrize("location", ["", "Anywhere"])
def test_empty_location_rules_accept_any_location(location):
    rules = MatchingRules(include_title=["python"])
    r = match(make_job("1", "Python Dev", location), rules)
    assert r.relevant is True
    assert r.reason == "title: python"


def test_empty_rules_everything_relevant():
    r = match(make_job("1", "Anything", "Anywhere"), MatchingRules())
    assert r.relevant is True
    assert r.reason == ""


@pytest.mark.parametrize("location, expected", [
    ("Singapore", True),
    ("London, Montreal, Singapore", True),  # multi-city strings
    ("REMOTE - APAC", True),
    ("New York", False),
    ("", True),  # unknown location: keep it visible rather than silently drop it
])
def test_in_my_locations(location, expected):
    rules = MatchingRules(include_title=["python"], include_location=["singapore", "remote"])
    assert in_my_locations(make_job("1", "Anything", location), rules) is expected


def test_in_my_locations_ignores_title_rules():
    rules = MatchingRules(include_title=["python"], exclude_title=["intern"], include_location=["singapore"])
    assert in_my_locations(make_job("1", "Intern Designer", "Singapore"), rules) is True


def test_in_my_locations_without_location_rules_keeps_everything():
    assert in_my_locations(make_job("1", "Anything", "Mars"), MatchingRules()) is True
