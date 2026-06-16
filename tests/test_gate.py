"""The gate must block a real reliability regression and pass a clean run."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gate, harness  # noqa: E402

BASELINE = {
    "metrics": {
        "n_questions": 14,
        "trust_rate": 0.786,
        "mean_accuracy": 0.91,
        "mean_flip_rate": 0.09,
    },
    "per_question": {
        "top_category": {"verdict": harness.STABLE_CORRECT, "accuracy": 1.0, "flip_rate": 0.0},
        "total_revenue": {"verdict": harness.FLAKY, "accuracy": 0.6, "flip_rate": 0.4},
    },
}


def test_passes_against_itself():
    result = gate.run_gate(BASELINE, BASELINE)
    assert result.passed
    assert result.checked >= 3


def test_blocks_a_question_that_regressed_from_stable_to_flaky():
    candidate = {
        "metrics": {"n_questions": 14, "trust_rate": 0.714, "mean_accuracy": 0.85, "mean_flip_rate": 0.18},
        "per_question": {
            "top_category": {"verdict": harness.FLAKY, "accuracy": 0.6, "flip_rate": 0.4},
            "total_revenue": {"verdict": harness.FLAKY, "accuracy": 0.6, "flip_rate": 0.4},
        },
    }
    result = gate.run_gate(BASELINE, candidate)
    assert not result.passed
    assert any("top_category regressed" in r for r in result.reasons)


def test_blocks_when_trust_rate_drops():
    candidate = {
        "metrics": {"n_questions": 14, "trust_rate": 0.50, "mean_accuracy": 0.91, "mean_flip_rate": 0.09},
        "per_question": BASELINE["per_question"],
    }
    result = gate.run_gate(BASELINE, candidate)
    assert not result.passed
    assert any("trust_rate dropped" in r for r in result.reasons)


def test_blocks_when_flip_rate_rises():
    candidate = {
        "metrics": {"n_questions": 14, "trust_rate": 0.786, "mean_accuracy": 0.91, "mean_flip_rate": 0.30},
        "per_question": BASELINE["per_question"],
    }
    result = gate.run_gate(BASELINE, candidate)
    assert not result.passed
    assert any("mean_flip_rate rose" in r for r in result.reasons)


def test_blocks_when_suite_shrinks():
    candidate = {
        "metrics": {"n_questions": 9, "trust_rate": 0.9, "mean_accuracy": 0.95, "mean_flip_rate": 0.02},
        "per_question": BASELINE["per_question"],
    }
    result = gate.run_gate(BASELINE, candidate)
    assert not result.passed
    assert any("covers 9 questions" in r for r in result.reasons)


def test_a_flaky_question_becoming_stable_is_not_a_regression():
    candidate = {
        "metrics": {"n_questions": 14, "trust_rate": 0.857, "mean_accuracy": 0.95, "mean_flip_rate": 0.04},
        "per_question": {
            "top_category": {"verdict": harness.STABLE_CORRECT, "accuracy": 1.0, "flip_rate": 0.0},
            "total_revenue": {"verdict": harness.STABLE_CORRECT, "accuracy": 1.0, "flip_rate": 0.0},
        },
    }
    result = gate.run_gate(BASELINE, candidate)
    assert result.passed  # improvement must never fail the gate


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
