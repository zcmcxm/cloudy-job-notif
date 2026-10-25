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
    assert (stored.first_seen, stored.status, stored.closed_at) == (T1, "open", None)


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
    assert stored.first_seen == T1


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
    assert by_id["1"].closed_at is None
    assert by_id["2"].first_seen == T1


def test_still_open_job_picks_up_edits(open_store):
    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1", title="Engineer")], T1)
    store.save()

    store = open_store()
    store.get_open_jobs("acme")
    store.record_seen([make_job("1", title="Senior Engineer")], T2)
    store.save()

    [stored] = open_store().get_open_jobs("acme")
    assert (stored.title, stored.first_seen) == ("Senior Engineer", T1)


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


def test_local_records_when_a_job_closed(tmp_path):
    path = tmp_path / "store.json"
    store = LocalJsonStore(path)
    store.record_seen([make_job("1")], T1)
    store.save()

    store = LocalJsonStore(path)
    store.get_open_jobs("acme")
    store.mark_closed([make_job("1")], T2)
    store.save()

    stored = LocalJsonStore(path)._data["acme"]["1"]
    assert (stored.status, stored.closed_at, stored.first_seen) == ("closed", T2, T1)


# --- DynamoStore only -------------------------------------------------------


@pytest.fixture
def job_writes(table, monkeypatch):
    """Counts JOB# items actually sent to DynamoDB (batch_writer and put_item both count)."""
    client = table.meta.client
    written = []
    real_batch, real_put = client.batch_write_item, client.put_item

    def batch(**kw):
        for requests in kw["RequestItems"].values():
            written.extend(r["PutRequest"]["Item"] for r in requests if "PutRequest" in r)
        return real_batch(**kw)

    def put(**kw):
        written.append(kw["Item"])
        return real_put(**kw)

    monkeypatch.setattr(client, "batch_write_item", batch)
    monkeypatch.setattr(client, "put_item", put)

    def job_ids():
        ids = sorted(i["SK"].removeprefix("JOB#") for i in written if i["SK"].startswith("JOB#"))
        written.clear()
        return ids

    return job_ids


def run(table, company, *, seen=(), closed=(), now):
    store = DynamoStore(table)
    store.get_open_jobs(company)
    store.record_seen(list(seen), now)
    store.mark_closed(list(closed), now)
    store.ensure_company(company)
    store.save()


def test_dynamo_unchanged_open_jobs_are_not_rewritten(table, job_writes):
    jobs = [make_job(str(i)) for i in range(5)]
    run(table, "acme", seen=jobs, now=T1)
    assert job_writes() == ["0", "1", "2", "3", "4"]  # first sighting: all written

    run(table, "acme", seen=jobs, now=T2)
    assert job_writes() == []  # nothing changed: no writes at all


def test_dynamo_writes_only_what_changed(table, job_writes):
    run(table, "acme", seen=[make_job("1"), make_job("2"), make_job("3")], now=T1)
    job_writes()

    run(table, "acme", now=T2,
        seen=[make_job("1"),                      # unchanged      -> no write
              make_job("2", title="Staff Eng"),   # edited         -> write
              make_job("4")],                     # new            -> write
        closed=[make_job("3")])                   # closed         -> write
    assert job_writes() == ["2", "3", "4"]


def test_dynamo_reopened_job_is_written(table, job_writes):
    run(table, "acme", seen=[make_job("1")], now=T1)
    run(table, "acme", closed=[make_job("1")], now=T2)
    job_writes()

    run(table, "acme", seen=[make_job("1")], now=T3)
    assert job_writes() == ["1"]
    [stored] = DynamoStore(table).get_open_jobs("acme")
    assert (stored.first_seen, stored.closed_at) == (T3, None)


def test_dynamo_records_when_a_job_closed(table):
    run(table, "acme", seen=[make_job("1")], now=T1)
    run(table, "acme", closed=[make_job("1")], now=T2)

    item = table.get_item(Key={"PK": "COMPANY#acme", "SK": "JOB#1"})["Item"]
    assert item["status"] == "closed"
    assert item["closed_at"].startswith("2026-10-06T00:00:00")
    assert "last_seen" not in item


def test_dynamo_reads_items_written_before_closed_at_existed(table):
    """Items deployed before this change carry last_seen and no closed_at: still readable."""
    table.put_item(Item={"PK": "COMPANY#acme", "SK": "JOB#1", "company_id": "acme", "job_id": "1",
                         "title": "Engineer", "location": "", "url": "https://example.com/1",
                         "department": "", "first_seen": "2026-10-05T00:00:00Z",
                         "last_seen": "2026-10-05T00:00:00Z", "status": "open"})
    [stored] = DynamoStore(table).get_open_jobs("acme")
    assert (stored.first_seen, stored.closed_at) == (T1, None)


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
