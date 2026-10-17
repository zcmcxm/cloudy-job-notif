"""Persistence between runs.

`Store` is the interface the runner depends on. Phase 1 uses LocalJsonStore;
Phase 2 adds a DynamoStore with the same methods (PK=COMPANY#<id>, SK=JOB#<job_id>).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

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
                **job.model_dump(), first_seen=first_seen, last_seen=now, status="open"
            )

    def mark_closed(self, jobs: list[Job], now: datetime) -> None:
        for job in jobs:
            stored = self._data.get(job.company_id, {}).get(job.job_id)
            if stored:
                stored.status = "closed"
                stored.last_seen = now

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
