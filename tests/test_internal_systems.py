from app.internal_systems import (
    estimate_aws_cost,
    list_meeting_assets,
    lookup_employee,
    query_internal_api,
)
from app.sandbox import SandboxError
import pytest


def test_lookup_employee_hit():
    hits = lookup_employee("林佳穎")
    assert hits[0]["id"] == "E001"


def test_internal_api_allowlist():
    with pytest.raises(SandboxError):
        query_internal_api("payroll", "bonus")


def test_internal_api_calendar():
    payload = query_internal_api("calendar", "Q2")
    assert payload["results"]


def test_s3_prefix_must_be_meetings():
    with pytest.raises(SandboxError):
        list_meeting_assets("secrets/")


def test_cost_estimate_positive():
    payload = estimate_aws_cost(vcpu=1, memory_gb=2, hours_per_month=730)
    assert 20 <= payload["total_usd"] <= 80
    assert payload["fargate_usd"] > 0
