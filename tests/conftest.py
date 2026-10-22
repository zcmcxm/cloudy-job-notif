import json
from pathlib import Path

import pytest
from moto import mock_aws

from job_alert.models import Job

FIXTURES = Path(__file__).parent / "fixtures"
REGION = "ap-southeast-2"


@pytest.fixture
def aws_env(monkeypatch):
    """Fake AWS (moto) with fake credentials, so nothing can ever reach a real account."""
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        yield


@pytest.fixture
def load_fixture():
    return lambda name: json.loads((FIXTURES / name).read_text())


def make_job(job_id: str, title: str = "Engineer", location: str = "", company_id: str = "acme") -> Job:
    return Job(company_id=company_id, job_id=job_id, title=title, location=location,
               url=f"https://example.com/{job_id}")
