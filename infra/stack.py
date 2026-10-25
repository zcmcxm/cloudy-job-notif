"""Everything the job alert needs in AWS, as one CDK stack.

    EventBridge Scheduler (daily, Asia/Singapore) ─▶ Lambda (job_alert.handler.handler)
                                                       ├─▶ DynamoDB table (DynamoStore)
                                                       └─▶ SES (send_ses)

Tests: `pytest tests/test_infra.py`. Deploy: `cdk synth` → `cdk diff` → `cdk deploy`.
API reference: https://docs.aws.amazon.com/cdk/api/v2/python/
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import BundlingOptions, CfnOutput, Duration, RemovalPolicy, Stack, TimeZone
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as targets
from aws_cdk import aws_ses as ses
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parent.parent


def lambda_code() -> lambda_.Code:
    """The deployment package: job_alert + its dependencies + config/, built for Linux arm64.

    Runs `pip install .` inside the official Lambda Python 3.13 build image (needs Docker
    running), so compiled wheels such as pydantic-core match the Lambda runtime, not your Mac.
    `config/companies.yaml` is copied next to the package, where handler.py looks for it.
    """
    return lambda_.Code.from_asset(
        str(REPO_ROOT),
        exclude=[".venv", ".git", ".data", "out", "cdk.out", "tests", "infra", ".pytest_cache",
                 "**/__pycache__", "*.egg-info", "PLAN.md"],
        bundling=BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_13.bundling_image,
            platform="linux/arm64",
            environment={"HOME": "/tmp"},  # the container runs as your uid, which has no home dir
            command=["bash", "-c", "pip install --no-cache-dir . -t /asset-output && cp -r config /asset-output/"],
        ),
    )


class JobAlertStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, alert_email: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Job history; must survive stack deletion
        dynamo_table = dynamodb.Table(self, "Jobs",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Function logs, kept two weeks
        log_group = logs.LogGroup(self, "RunnerLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # The daily run
        fn = lambda_.Function(self, "Runner",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_code(),
            handler="job_alert.handler.handler",
            memory_size=512,
            timeout=Duration.minutes(5),
            retry_attempts=0,
            log_group=log_group,
            logging_format=lambda_.LoggingFormat.JSON,
            environment={
                "TABLE_NAME": dynamo_table.table_name,
                "SENDER": alert_email,
                "RECIPIENT": alert_email,
            },
        )

        # Sender/recipient identity (AWS emails a verification link on first deploy)
        ses_identity = ses.EmailIdentity(self, "Sender", identity=ses.Identity.email(alert_email))

        # Permissions via grants: no hand-written IAM
        dynamo_table.grant_read_write_data(fn)
        ses_identity.grant_send_email(fn)

        # 08:00 Singapore time, every day
        scheduler.Schedule(self, "Daily",
            schedule=scheduler.ScheduleExpression.cron(hour="8", minute="0", time_zone=TimeZone.ASIA_SINGAPORE),
            target=targets.LambdaInvoke(fn, retry_attempts=0),
        )

        # Names for `aws lambda invoke` / the console
        CfnOutput(self, "FunctionName", value=fn.function_name, description="Lambda function name")
        CfnOutput(self, "TableName", value=dynamo_table.table_name, description="DynamoDB table name")
