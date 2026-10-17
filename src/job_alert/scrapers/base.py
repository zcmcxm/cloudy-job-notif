from __future__ import annotations

from typing import Any, Protocol

import httpx

from job_alert.models import CompanyConfig, Job

USER_AGENT = "cloudy-job-notif/0.1 (personal job alert; low frequency)"


class Scraper(Protocol):
    def __call__(self, company: CompanyConfig, client: httpx.Client) -> list[Job]: ...


def make_client() -> httpx.Client:
    """Shared HTTP client: polite UA, sane timeouts, one retry on connection errors."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        transport=httpx.HTTPTransport(retries=1),
    )


def require_token(company: CompanyConfig) -> str:
    if not company.token:
        raise ValueError(f"{company.id}: scraper type {company.type!r} needs `token` in config")
    return company.token


def require_url(company: CompanyConfig) -> str:
    if not company.url:
        raise ValueError(f"{company.id}: scraper type {company.type!r} needs `url` in config")
    return company.url.rstrip("/")


def require_option(company: CompanyConfig, key: str) -> Any:
    if key not in company.options:
        raise ValueError(f"{company.id}: scraper type {company.type!r} needs `options.{key}` in config")
    return company.options[key]
