from evals.runner import run


def test_golden_eval_suite_passes():
    summary = run()
    assert summary["failed"] == [], summary
    assert summary["passed"] == summary["total"]
