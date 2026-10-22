"""send_ses against SES faked by moto (rejects unverified senders, like the real sandbox)."""

import boto3
import pytest
from botocore.exceptions import ClientError
from conftest import REGION
from moto.core import DEFAULT_ACCOUNT_ID
from moto.ses.models import ses_backends
from test_notifier import _report

from job_alert.notifier import render_text, send_ses

SENDER = "alerts@example.com"
RECIPIENT = "me@example.com"
SUBJECT = "Job alert: 1 relevant open — ⭐"
HTML = "<h2>Job alert ⭐</h2>"
TEXT = "Job alert\n"


@pytest.fixture
def ses(aws_env):
    client = boto3.client("sesv2", region_name=REGION)
    client.create_email_identity(EmailIdentity=SENDER)  # the CDK app does this for real
    return client


def sent_messages():
    return ses_backends[DEFAULT_ACCOUNT_ID][REGION].sent_messages


def test_sends_html_email_to_recipient(ses):
    message_id = send_ses(SUBJECT, HTML, TEXT, sender=SENDER, recipient=RECIPIENT, client=ses)

    assert message_id
    [msg] = sent_messages()
    assert msg.source == SENDER
    assert msg.destinations == {"ToAddresses": [RECIPIENT]}
    assert msg.subject == SUBJECT
    assert msg.body == HTML


def test_includes_plain_text_part_as_utf8(ses, monkeypatch):
    calls = []
    real_send = ses.send_email
    monkeypatch.setattr(ses, "send_email", lambda **kw: calls.append(kw) or real_send(**kw))

    send_ses(SUBJECT, HTML, TEXT, sender=SENDER, recipient=RECIPIENT, client=ses)

    [kw] = calls
    body = kw["Content"]["Simple"]["Body"]
    assert body["Text"]["Data"] == TEXT
    assert body["Html"]["Charset"] == body["Text"]["Charset"] == "UTF-8"


def test_creates_its_own_client_when_none_given(ses):
    send_ses(SUBJECT, HTML, TEXT, sender=SENDER, recipient=RECIPIENT)
    assert len(sent_messages()) == 1


def test_errors_propagate(ses):
    """An unverified sender must raise, so the handler skips saving and retries next run."""
    with pytest.raises(ClientError) as e:
        send_ses(SUBJECT, HTML, TEXT, sender="unverified@example.com", recipient=RECIPIENT, client=ses)
    assert e.value.response["Error"]["Code"] == "MessageRejected"
    assert sent_messages() == []


def test_render_text_lists_relevant_roles_and_errors():
    text = render_text(_report())
    assert text.startswith("Job alert: 2 relevant open (1 new)")
    assert "- Python Lead — Acme" in text
    assert "https://example.com/1" in text
    assert "! Broken Co: HTTPStatusError: 404" in text
