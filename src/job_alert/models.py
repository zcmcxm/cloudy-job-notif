"""Core data types shared by every module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Job(BaseModel):
    """One job posting as scraped from a careers site."""

    company_id: str
    job_id: str  # stable id from the careers platform
    title: str
    location: str = ""
    url: str
    department: str = ""


class StoredJob(Job):
    """A Job plus the bookkeeping the store keeps between runs."""

    first_seen: datetime
    last_seen: datetime
    status: str = "open"  # "open" | "closed"


class CompanyConfig(BaseModel):
    id: str
    name: str
    type: str  # scraper adapter name, e.g. "greenhouse"
    token: str | None = None  # board slug for ATS adapters
    url: str | None = None  # careers site base URL (eightfold)
    options: dict[str, Any] = Field(default_factory=dict)  # adapter-specific extras (see each adapter)


class MatchingRules(BaseModel):
    include_title: list[str] = Field(default_factory=list)
    exclude_title: list[str] = Field(default_factory=list)
    include_location: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    companies: list[CompanyConfig]
    matching: MatchingRules = Field(default_factory=MatchingRules)


class MatchResult(BaseModel):
    relevant: bool
    reason: str = ""  # e.g. "title: python; location: remote"


class MatchedJob(BaseModel):
    job: Job
    match: MatchResult
    is_new: bool = False  # first seen this run
    open_since: datetime | None = None  # when this app first saw the role open


class CompanyResult(BaseModel):
    """Outcome of one company in one run; this is what the digest renders."""

    company: CompanyConfig
    total_open: int = 0  # open roles in your locations
    new: list[MatchedJob] = Field(default_factory=list)  # new roles in your locations
    relevant_open: list[MatchedJob] = Field(default_factory=list)  # every open relevant role in your locations
    closed: list[Job] = Field(default_factory=list)  # closed roles in your locations
    hidden_new: int = 0  # new roles outside your locations: stored, but not listed
    baseline: bool = False  # first time we've seen this company: "new" is everything
    error: str | None = None


class RunReport(BaseModel):
    started_at: datetime
    results: list[CompanyResult]

    @property
    def relevant_open(self) -> list[tuple[CompanyConfig, MatchedJob]]:
        """All open relevant roles; new ones first (baseline runs don't count as new)."""
        roles = [(r.company, m, m.is_new and not r.baseline) for r in self.results for m in r.relevant_open]
        return [(c, m) for c, m, _ in sorted(roles, key=lambda t: not t[2])]  # stable sort keeps company order

    @property
    def relevant_new_count(self) -> int:
        return sum(1 for r in self.results if not r.baseline for m in r.relevant_open if m.is_new)

    @property
    def hidden_new(self) -> int:
        return sum(r.hidden_new for r in self.results if not r.baseline)

    @property
    def errors(self) -> list[CompanyResult]:
        return [r for r in self.results if r.error]
