"""Offline eval runner for sandbox, MCP-shaped tools, report structure, and traces."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.internal_systems import estimate_aws_cost, list_meeting_assets, query_internal_api
from app.sandbox import SandboxError, resolve_sandbox_path, sandbox_root

GOLDEN = Path(__file__).resolve().parent / "golden_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


def _denied(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return False
    except SandboxError:
        return True


def eval_sandbox(case: dict[str, Any]) -> tuple[bool, str]:
    denied = _denied(resolve_sandbox_path, case["path"], must_exist=False, allow_create=True)
    ok = denied if case["expect"] == "deny" else not denied
    return ok, "denied" if denied else "allowed"


def eval_internal_api(case: dict[str, Any]) -> tuple[bool, str]:
    try:
        payload = query_internal_api(case["resource"], case["query"])
    except SandboxError as exc:
        if case["expect"] == "deny":
            return True, str(exc)
        return False, str(exc)
    blob = json.dumps(payload, ensure_ascii=False)
    if case["expect"] == "deny":
        return False, blob
    if case.get("contains") and case["contains"] not in blob:
        return False, blob
    return True, blob


def eval_s3(case: dict[str, Any]) -> tuple[bool, str]:
    try:
        payload = list_meeting_assets(case["prefix"])
    except SandboxError as exc:
        return case["expect"] == "deny", str(exc)
    if case["expect"] == "deny":
        return False, json.dumps(payload)
    return True, json.dumps(payload)


def eval_report_sections(case: dict[str, Any]) -> tuple[bool, str]:
    text = (ROOT / case["fixture"]).read_text(encoding="utf-8")
    missing = [section for section in case["required_sections"] if section not in text]
    return not missing, f"missing={missing}"


def eval_tool_trace(case: dict[str, Any]) -> tuple[bool, str]:
    trace = json.loads((ROOT / case["fixture"]).read_text(encoding="utf-8"))
    used = set(trace.get("tools_used") or [])
    expected = case["expected_tools"]
    hits = sum(1 for name in expected if name in used)
    recall = hits / max(len(expected), 1)
    return recall >= float(case["min_recall"]), f"recall={recall:.2f} used={sorted(used)}"


def eval_aws_cost(case: dict[str, Any]) -> tuple[bool, str]:
    payload = estimate_aws_cost(
        vcpu=case["vcpu"],
        memory_gb=case["memory_gb"],
        hours_per_month=case["hours_per_month"],
    )
    total = payload["total_usd"]
    ok = case["min_total"] <= total <= case["max_total"]
    return ok, f"total_usd={total}"


EVALUATORS = {
    "sandbox": eval_sandbox,
    "internal_api": eval_internal_api,
    "s3": eval_s3,
    "report_sections": eval_report_sections,
    "tool_trace": eval_tool_trace,
    "aws_cost": eval_aws_cost,
}


def run() -> dict[str, Any]:
    sandbox_root()
    results = []
    passed = 0
    for case in _load_cases():
        evaluator = EVALUATORS[case["type"]]
        ok, detail = evaluator(case)
        passed += int(ok)
        results.append({"id": case["id"], "ok": ok, "detail": detail})
    summary = {
        "passed": passed,
        "total": len(results),
        "failed": [item["id"] for item in results if not item["ok"]],
        "results": results,
    }
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "last-run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    summary = run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
