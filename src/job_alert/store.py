"""Persistence between runs.

`Store` is the interface the runner depends on. LocalJsonStore runs on your machine;
DynamoStore keeps the same data in a DynamoDB table for the Lambda.

Call order per company, as runner._run_company does it:
    has_company -> get_open_jobs -> record_seen / mark_closed -> ensure_company
and `save()` once at the end of the run. Nothing is persisted before `save()`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from boto3.dynamodb.conditions import Key

from job_alert.models import Job, StoredJob


class Store(Protocol):
    def has_company(self, company_id: str) -> bool: ...
    def get_open_jobs(self, company_id: str) -> list[StoredJob]: ...
    def record_seen(self, jobs: list[Job], now: datetime) -> None: ...
    def mark_closed(self, jobs: list[Job], now: datetime) -> None: ...
    def ensure_company(self, company_id: str) -> None: ...
    def save(self) -> None: ...


class LocalJsonStore:
    """{company_id: {job_id: StoredJob-as-dict}} in a single JSON file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        raw = json.loads(self.path.read_text()) if self.path.exists() else {}
        self._data: dict[str, dict[str, StoredJob]] = {
            cid: {jid: StoredJob.model_validate(j) for jid, j in jobs.items()}
            for cid, jobs in raw.items()
        }

    def has_company(self, company_id: str) -> bool:
        return company_id in self._data

    def get_open_jobs(self, company_id: str) -> list[StoredJob]:
        return [j for j in self._data.get(company_id, {}).values() if j.status == "open"]

    def record_seen(self, jobs: list[Job], now: datetime) -> None:
        for job in jobs:
            bucket = self._data.setdefault(job.company_id, {})
            prev = bucket.get(job.job_id)
            first_seen = prev.first_seen if prev and prev.status == "open" else now
            bucket[job.job_id] = StoredJob(
                **job.model_dump(), first_seen=first_seen, status="open"
            )

    def mark_closed(self, jobs: list[Job], now: datetime) -> None:
        for job in jobs:
            stored = self._data.get(job.company_id, {}).get(job.job_id)
            if stored:
                stored.status = "closed"
                stored.closed_at = now

    def ensure_company(self, company_id: str) -> None:
        """Remember a company even when it currently has zero openings."""
        self._data.setdefault(company_id, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            cid: {jid: j.model_dump(mode="json") for jid, j in jobs.items()}
            for cid, jobs in self._data.items()
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))


class DynamoStore:
    """Same behaviour as LocalJsonStore, backed by one DynamoDB table.

    Table layout (single-table design, keys are strings):
        PK = "COMPANY#<company_id>"   SK = "META"            marker: company is known
        PK = "COMPANY#<company_id>"   SK = "JOB#<job_id>"    one item per job ever seen

    Job items carry every StoredJob field (see `_to_item`). Reads go straight to the
    table; writes are buffered in `self._pending` and flushed by `save()`.
    """

    def __init__(self, table: Any):  # boto3.resource("dynamodb").Table(name)
        self.table = table
        self._pending: dict[tuple[str, str], dict[str, Any]] = {}  # (PK, SK) -> item to put
        # The runner always calls get_open_jobs(company) before record_seen/mark_closed for
        # that company, so remembering what get_open_jobs returned saves extra reads later.
        self._open: dict[str, dict[str, StoredJob]] = {}  # company_id -> {job_id: StoredJob}

    def has_company(self, company_id: str) -> bool:
        return self.table.get_item(Key={"PK": _pk(company_id), "SK": "META"}).get("Item") is not None

    def get_open_jobs(self, company_id: str) -> list[StoredJob]:
        kwargs = {"KeyConditionExpression": Key("PK").eq(_pk(company_id)) & Key("SK").begins_with("JOB#")}
        while True:
            resp = self.table.query(**kwargs)
            items = resp.get("Items", [])
            if company_id not in self._open:
                self._open[company_id] = {item["SK"][4:]: _from_item(item) for item in items if item.get("status") == "open"}
            else:
                self._open[company_id].update({item["SK"][4:]: _from_item(item) for item in items if item.get("status") == "open"})
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return list(self._open[company_id].values())

    def record_seen(self, jobs: list[Job], now: datetime) -> None:
        for job in jobs:
            prev = self._open.get(job.company_id, {}).get(job.job_id)
            if prev and prev.status == "open" and prev.model_dump(include=set(Job.model_fields)) == job.model_dump():
                continue  # still open and unchanged: skip the write
            stored_job = StoredJob(**job.model_dump(), first_seen=prev.first_seen if prev and prev.status == "open" else now, status="open")
            self._pending[(_pk(job.company_id), _sk(job.job_id))] = _to_item(stored_job)

    def mark_closed(self, jobs: list[Job], now: datetime) -> None:
        for job in jobs:
            stored = self._open.get(job.company_id, {}).get(job.job_id)
            if stored:
                stored.status = "closed"
                stored.closed_at = now
                self._pending[(_pk(job.company_id), _sk(job.job_id))] = _to_item(stored)

    def ensure_company(self, company_id: str) -> None:
        self._pending[(_pk(company_id), "META")] = {"PK": _pk(company_id), "SK": "META"}

    def save(self) -> None:
        with self.table.batch_writer() as batch:
            for item in self._pending.values():
                batch.put_item(Item=item)
        self._pending.clear()


def _pk(company_id: str) -> str:
    return f"COMPANY#{company_id}"


def _sk(job_id: str) -> str:
    return f"JOB#{job_id}"


def _to_item(job: StoredJob) -> dict[str, Any]:
    """StoredJob -> DynamoDB item. Datetimes become ISO-8601 strings."""
    return {"PK": _pk(job.company_id), "SK": _sk(job.job_id), **job.model_dump(mode="json")}


def _from_item(item: dict[str, Any]) -> StoredJob:
    """DynamoDB item -> StoredJob (pydantic ignores PK/SK and parses the ISO strings)."""
    return StoredJob.model_validate(item)
