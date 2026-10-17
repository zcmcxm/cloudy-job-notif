from conftest import make_job

from job_alert.diff import compute_diff, is_suspicious_empty


def ids(jobs):
    return [j.job_id for j in jobs]


def test_all_new_when_nothing_stored():
    d = compute_diff([make_job("1"), make_job("2")], [])
    assert ids(d.new) == ["1", "2"]
    assert d.closed == [] and d.still_open == []


def test_new_closed_and_still_open():
    stored = [make_job("1"), make_job("2")]
    current = [make_job("2"), make_job("3")]
    d = compute_diff(current, stored)
    assert ids(d.new) == ["3"]
    assert ids(d.closed) == ["1"]
    assert ids(d.still_open) == ["2"]


def test_still_open_uses_current_version():
    d = compute_diff([make_job("1", title="Renamed")], [make_job("1", title="Old")])
    assert d.still_open[0].title == "Renamed"


def test_preserves_current_order():
    d = compute_diff([make_job("c"), make_job("a"), make_job("b")], [])
    assert ids(d.new) == ["c", "a", "b"]


def test_duplicate_ids_in_current_appear_once():
    d = compute_diff([make_job("1"), make_job("1")], [])
    assert ids(d.new) == ["1"]


def test_suspicious_empty():
    assert is_suspicious_empty([], [make_job("1")]) is True
    assert is_suspicious_empty([], []) is False
    assert is_suspicious_empty([make_job("1")], [make_job("1")]) is False
