"""Render the run report as an HTML email. Phase 2 adds `send_ses(html, ...)`."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Environment, PackageLoader, select_autoescape

from job_alert.models import RunReport

_env = Environment(
    loader=PackageLoader("job_alert", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def open_since(since: datetime | None, now: datetime) -> str:
    """'open since 5 Oct 2026 (9 days)'; 'open since today' for roles first seen this run."""
    if since is None:
        return ""
    days = (now - since).days
    if days < 1:
        return "open since today"
    return f"open since {since.day} {since:%b %Y} ({days} day{'s' if days != 1 else ''})"


_env.filters["open_since"] = open_since


def subject(report: RunReport) -> str:
    new = sum(len(r.new) for r in report.results if not r.baseline)
    relevant_open = len(report.relevant_open)
    errors = len(report.errors)
    parts = [
        f"{relevant_open} relevant open ({report.relevant_new_count} new)",
        f"{new} new role{'s' if new != 1 else ''} overall",
    ]
    if errors:
        parts.append(f"{errors} scrape problem{'s' if errors != 1 else ''}")
    return "Job alert: " + ", ".join(parts)


def render_html(report: RunReport) -> str:
    baseline_ids = {r.company.id for r in report.results if r.baseline}
    return _env.get_template("digest.html.j2").render(
        report=report, subject=subject(report), baseline_ids=baseline_ids
    )
