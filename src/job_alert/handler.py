"""AWS Lambda entry point: one scheduled run = scrape, email the digest, then save state.

Environment (set by the CDK stack):
    TABLE_NAME    DynamoDB table for DynamoStore
    SENDER        verified SES identity the digest is sent from
    RECIPIENT     where the digest goes
    CONFIG_PATH   companies.yaml inside the deployment package (default: config/companies.yaml,
                  relative to the Lambda task root, which is the working directory)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import boto3

from job_alert.config import load_config
from job_alert.models import AppConfig, RunReport
from job_alert.notifier import render_html, render_text, send_ses, subject
from job_alert.runner import run
from job_alert.scrapers.base import make_client
from job_alert.store import DynamoStore

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)  # Lambda's root handler is already configured; just set our level


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config(os.environ.get("CONFIG_PATH", "config/companies.yaml"))
    store = DynamoStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))

    report = asyncio.run(_scrape(config, store))

    subj = subject(report)
    message_id = send_ses(
        subj, render_html(report), render_text(report),
        sender=os.environ["SENDER"], recipient=os.environ["RECIPIENT"],
    )
    # Only after the email is out: if sending raised, nothing is saved and the next run
    # reports the same new roles again instead of silently dropping them.
    store.save()

    errors = [r.company.id for r in report.errors]
    log.info("digest sent", extra={"subject": subj, "message_id": message_id, "scrape_errors": errors})
    return {"subject": subj, "message_id": message_id, "scrape_errors": errors}


async def _scrape(config: AppConfig, store: DynamoStore) -> RunReport:
    # A fresh event loop per invocation (asyncio.run), and the client lives inside it.
    async with make_client() as http:
        return await run(config, store, http)
