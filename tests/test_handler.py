"""The Lambda handler end to end: fake scraper, moto DynamoDB + SES, real runner and store."""

import boto3
import pytest
from botocore.exceptions import ClientError
from conftest import REGION, make_job
from moto.core import DEFAULT_ACCOUNT_ID
from moto.ses.models import ses_backends
from test_store import create_table

from job_alert import runner
from job_alert.handler import handler
from job_alert.store import DynamoStore

SENDER = "alerts@example.com"
RECIPIENT = "me@example.com"
CONFIG = """
companies:
  - {id: acme, name: Acme, type: fake}
matching:
  include_title: [python]
"""


@pytest.fixture
def env(aws_env, tmp_path, monkeypatch):
    table = create_table()
    boto3.client("sesv2", region_name=REGION).create_email_identity(EmailIdentity=SENDER)
    config = tmp_path / "companies.yaml"
    config.write_text(CONFIG)
    for k, v in {"TABLE_NAME": table.name, "SENDER": SENDER, "RECIPIENT": RECIPIENT,
                 "CONFIG_PATH": str(config)}.items():
        monkeypatch.setenv(k, v)

    scraped = {"jobs": []}
    monkeypatch.setattr(runner, "get_scraper", lambda type_: lambda company, client: scraped["jobs"])
    return scraped, table


def sent_messages():
    return ses_backends[DEFAULT_ACCOUNT_ID][REGION].sent_messages


def test_sends_digest_then_saves_state(env):
    scraped, table = env
    scraped["jobs"] = [make_job("1", "Python Dev"), make_job("2", "Designer")]

    result = handler({}, None)

    [msg] = sent_messages()
    assert msg.destinations == {"ToAddresses": [RECIPIENT]}
    assert msg.subject == result["subject"]
    assert "Python Dev" in msg.body
    assert result["message_id"] and result["scrape_errors"] == []
    store = DynamoStore(table)
    assert store.has_company("acme")
    assert {j.job_id for j in store.get_open_jobs("acme")} == {"1", "2"}


def test_second_run_reports_only_new_roles(env):
    scraped, _ = env
    scraped["jobs"] = [make_job("1", "Python Dev")]
    handler({}, None)

    scraped["jobs"] = [make_job("1", "Python Dev"), make_job("3", "Python Lead")]
    result = handler({}, None)

    assert "1 new role overall" in result["subject"]


def test_failed_send_saves_nothing(env, monkeypatch):
    scraped, table = env
    scraped["jobs"] = [make_job("1", "Python Dev")]
    monkeypatch.setenv("SENDER", "unverified@example.com")

    with pytest.raises(ClientError):
        handler({}, None)

    assert not DynamoStore(table).has_company("acme")  # next run will report role 1 again


def test_scrape_errors_are_reported_not_raised(env, monkeypatch):
    def broken(company, client):
        raise RuntimeError("site down")

    monkeypatch.setattr(runner, "get_scraper", lambda type_: broken)

    result = handler({}, None)

    assert result["scrape_errors"] == ["acme"]
    assert len(sent_messages()) == 1  # you still get the digest, with the problem listed
