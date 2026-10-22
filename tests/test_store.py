"""Store contract: LocalJsonStore and DynamoStore must behave the same.

Every test below runs against both stores. Each "run" opens a fresh store instance on the
same backing data (JSON file / DynamoDB table), the way the CLI and the Lambda do, and
calls methods in runner order: has_company -> get_open_jobs -> record_seen / mark_closed
-> ensure_company -> save.

DynamoDB is faked in-process by moto: no AWS account or network needed.
"""

from datetime import datetime, timezone

import boto3
import pytest
from conftest import REGION, make_job

from job_alert.store import DynamoStore, LocalJsonStore

T1 = datetime(2026, 10, 5, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 6, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 7, tzinfo=timezone.utc)

TABLE = "job-alert-test"


def create_table():
    """Same key schema as the CDK table in infra/."""
    ddb = boto3.resource("dynamodb", region_name=REGION)
    return ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def table(aws_env):
    return create_table()


@pytest.fixture(params=["local", "dynamo"])
def open_store(request, tmp_path):
    """Returns a function that opens a fresh store on the same data, like a new run."""
    if request.param == "local":
        path = tmp_path / "store.json"
        return lambda: LocalJsonStore(path)
    table = request.getfixturevalue("table")
    return lambda: DynamoStore(table)


def ids(jobs):
    return sorted(j.job_id for j in jobs)


def test_empty_store(open_store):
    store = open_store()
    assert not store.has_company("acme")
    assert store.get_open_jobs("acme") == []


def test_company_with_no_jobs_is_remembered(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.ensure_company("acme")
    store.save()

    store = open_store()
    assert store.has_company("acme")
    assert store.get_open_jobs("acme") == []


def test_nothing_persisted_before_save(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1")], T1)
    store.ensure_company("acme")
    # no save()

    store = open_store()
    assert not store.has_company("acme")
    assert store.get_open_jobs("acme") == []


def test_record_seen_round_trips_all_fields(open_store):
    job = make_job("1", title="Python Dev", location="Singapore")
    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([job], T1)
    store.ensure_company("acme")
    store.save()

    [stored] = open_store().get_open_jobs("acme")
    assert stored.model_dump(include=set(type(job).model_fields)) == job.model_dump()
    assert (stored.first_seen, stored.last_seen, stored.status) == (T1, T1, "open")


def test_still_open_keeps_first_seen(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1")], T1)
    store.save()

    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1")], T2)
    store.save()

    [stored] = open_store().get_open_jobs("acme")
    assert (stored.first_seen, stored.last_seen) == (T1, T2)


def test_closed_jobs_are_not_open_and_reopen_counts_as_new(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1"), make_job("2")], T1)
    store.save()

    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("2")], T2)
    store.mark_closed([make_job("1")], T2)
    store.save()
    assert ids(open_store().get_open_jobs("acme")) == ["2"]

    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1"), make_job("2")], T3)
    store.save()

    by_id = {j.job_id: j for j in open_store().get_open_jobs("acme")}
    assert by_id["1"].first_seen == T3  # reopened: the clock restarts
    assert by_id["2"].first_seen == T1


def test_companies_are_isolated(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.get_open_jobs("globex")
    store.record_seen([make_job("1", company_id="acme"), make_job("2", company_id="globex")], T1)
    store.ensure_company("acme")
    store.save()

    store = open_store()
    assert ids(store.get_open_jobs("acme")) == ["1"]
    assert ids(store.get_open_jobs("globex")) == ["2"]


# --- DynamoStore only -------------------------------------------------------


def test_dynamo_item_layout(table):
    """infra/ and any later tooling rely on this key layout."""
    store = DynamoStore(table)
    store.get_open_jobs("acme")
    store.record_seen([make_job("1")], T1)
    store.ensure_company("acme")
    store.save()

    assert "Item" in table.get_item(Key={"PK": "COMPANY#acme", "SK": "META"})
    item = table.get_item(Key={"PK": "COMPANY#acme", "SK": "JOB#1"})["Item"]
    assert item["status"] == "open"
    assert item["first_seen"].startswith("2026-10-05T00:00:00")


def test_dynamo_get_open_jobs_follows_pagination(table):
    """A single Query returns at most 1 MB; big companies need several pages."""
    jobs = [make_job(str(i), title="x" * 4000) for i in range(300)]  # ~1.2 MB of items
    store = DynamoStore(table)
    store.get_open_jobs("acme")
    store.record_seen(jobs, T1)
    store.save()

    assert len(DynamoStore(table).get_open_jobs("acme")) == 300
