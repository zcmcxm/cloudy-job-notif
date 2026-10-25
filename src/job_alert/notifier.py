"""Render the run report as an email (HTML + plain-text fallback) and send it with SES."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import boto3
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


def render_text(report: RunReport) -> str:
    """Plain-text part of the email, for clients that don't show HTML: the relevant roles."""
    lines = [subject(report), ""]
    for company, m in report.relevant_open:
        lines.append(f"- {m.job.title} — {company.name}" + (f", {m.job.location}" if m.job.location else ""))
        lines.append(f"  {m.job.url}")
    if not report.relevant_open:
        lines.append("No open roles match your rules.")
    if report.stale_relevant:
        lines.append(f"({report.stale_relevant} relevant open more than {report.stale_after_days} days hidden as stale)")
    for r in report.errors:
        lines.append(f"! {r.company.name}: {r.error}")
    return "\n".join(lines) + "\n"


def send_ses(subject: str, html: str, text: str, *, sender: str, recipient: str, client: Any = None) -> str:
    """Email the digest through SES v2 and return the SES MessageId.

    `sender` must be a verified SES identity (in the sandbox, `recipient` too).
    `client` is a boto3 "sesv2" client; create one when it's None.
    Don't catch errors here: if sending fails, the handler must not save the store,
    so the same new roles are reported again on the next run.
    """
    client = client or boto3.client("sesv2")
    resp = client.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [recipient]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html, "Charset": "UTF-8"},
                    "Text": {"Data": text, "Charset": "UTF-8"},
                },
            }
        },
    )
    return resp["MessageId"]
