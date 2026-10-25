"""Assertions on the CloudFormation template that infra/stack.py synthesizes.

No AWS calls and no Docker: Lambda bundling is skipped (the asset is just hashed), so this
checks *what* would be deployed, not that the package builds. `cdk synth` checks that.
"""

import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template

from infra.stack import JobAlertStack

EMAIL = "me@example.com"


@pytest.fixture(scope="module")
def template():
    app = App(context={"aws:cdk:bundling-stacks": []})  # skip Docker bundling
    stack = JobAlertStack(app, "Test", env=Environment(account="111111111111", region="ap-southeast-2"),
                          alert_email=EMAIL)
    return Template.from_stack(stack)


def only(template, type_):
    resources = template.find_resources(type_)
    assert len(resources) == 1, f"expected exactly one {type_}, found {len(resources)}"
    [(logical_id, resource)] = resources.items()
    return logical_id, resource


def policy_statements(template):
    return [s for p in template.find_resources("AWS::IAM::Policy").values()
            for s in p["Properties"]["PolicyDocument"]["Statement"]]


def actions(statement):
    a = statement["Action"]
    return {a} if isinstance(a, str) else set(a)


# --- TODO(1) table ---------------------------------------------------------------

def test_table_matches_dynamostore_layout(template):
    _, table = only(template, "AWS::DynamoDB::Table")
    props = table["Properties"]
    assert sorted((k["AttributeName"], k["KeyType"]) for k in props["KeySchema"]) == [("PK", "HASH"), ("SK", "RANGE")]
    assert {(a["AttributeName"], a["AttributeType"]) for a in props["AttributeDefinitions"]} == {("PK", "S"), ("SK", "S")}
    assert props["BillingMode"] == "PAY_PER_REQUEST"


def test_table_survives_stack_deletion(template):
    _, table = only(template, "AWS::DynamoDB::Table")
    assert table["DeletionPolicy"] == "Retain"
    assert table["UpdateReplacePolicy"] == "Retain"


# --- TODO(2) + (3) function and logs ---------------------------------------------

def test_function_runtime_and_size(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Runtime": "python3.13",
        "Architectures": ["arm64"],
        "Handler": "job_alert.handler.handler",
        "MemorySize": 512,
        "Timeout": 300,
    })


def test_function_environment(template):
    table_id, _ = only(template, "AWS::DynamoDB::Table")
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": {"Variables": {"TABLE_NAME": {"Ref": table_id}, "SENDER": EMAIL, "RECIPIENT": EMAIL}},
    })


def test_function_logs_json_to_two_week_log_group(template):
    log_id, _ = only(template, "AWS::Logs::LogGroup")
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 14})
    template.has_resource_properties("AWS::Lambda::Function", {
        "LoggingConfig": {"LogFormat": "JSON", "LogGroup": {"Ref": log_id}},
    })


def test_function_does_not_retry(template):
    template.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


# --- TODO(4) + (5) SES and permissions -------------------------------------------

def test_ses_identity_for_alert_email(template):
    template.has_resource_properties("AWS::SES::EmailIdentity", {"EmailIdentity": EMAIL})


def test_function_can_read_and_write_the_table(template):
    table_id, _ = only(template, "AWS::DynamoDB::Table")
    granted = set().union(*(actions(s) for s in policy_statements(template)
                            if {"Fn::GetAtt": [table_id, "Arn"]} in _as_list(s["Resource"])))
    assert {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchWriteItem"} <= granted


def test_function_can_send_email(template):
    granted = set().union(set(), *(actions(s) for s in policy_statements(template)))
    assert "ses:SendEmail" in granted


def test_no_wildcard_permissions(template):
    for s in policy_statements(template):
        assert "*" not in _as_list(s["Resource"]), f"statement grants on every resource: {s}"


# --- TODO(6) schedule ------------------------------------------------------------

def test_daily_schedule_at_8am_singapore(template):
    fn_id, _ = only(template, "AWS::Lambda::Function")
    template.has_resource_properties("AWS::Scheduler::Schedule", {
        "ScheduleExpression": "cron(0 8 * * ? *)",
        "ScheduleExpressionTimezone": "Asia/Singapore",
        "State": "ENABLED",
        "Target": Match.object_like({"Arn": {"Fn::GetAtt": [fn_id, "Arn"]}}),
    })


# --- TODO(7) outputs -------------------------------------------------------------

def test_outputs_for_cli_use(template):
    outputs = template.find_outputs("*")
    assert {"FunctionName", "TableName"} <= set(outputs)


def _as_list(value):
    return value if isinstance(value, list) else [value]
