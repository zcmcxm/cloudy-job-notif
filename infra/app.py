"""CDK app entry point. Run `cdk synth | diff | deploy` from the repo root (see cdk.json).

Nothing account-specific lives in the repo:
    CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION   filled in by the CDK CLI from your AWS profile
    ALERT_EMAIL                                 address the digest is sent from and to
e.g.  AWS_PROFILE=cloudy ALERT_EMAIL=you@example.com cdk diff
"""

from __future__ import annotations

import os
import sys

from aws_cdk import App, Environment

from infra.stack import JobAlertStack


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set (see infra/app.py)")
    return value


app = App()
JobAlertStack(
    app,
    "JobAlert",
    env=Environment(account=require_env("CDK_DEFAULT_ACCOUNT"), region=require_env("CDK_DEFAULT_REGION")),
    alert_email=require_env("ALERT_EMAIL"),
)
app.synth()
