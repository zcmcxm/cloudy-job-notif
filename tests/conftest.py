import json
from pathlib import Path

import pytest

from job_alert.models import Job

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    return lambda name: json.loads((FIXTURES / name).read_text())


def make_job(job_id: str, title: str = "Engineer", location: str = "", company_id: str = "acme") -> Job:
    return Job(company_id=company_id, job_id=job_id, title=title, location=location,
               url=f"https://example.com/{job_id}")
