"""The release gate: may this candidate prompt/model replace the baseline?

Every prompt tweak and model upgrade raises the same question: did anything get
WORSE? A candidate can lift single-run accuracy while quietly making a question
flap. Averages hide it. So the gate compares against a committed baseline and
fails loudly when:

  * trust_rate or mean_accuracy drops more than MAX_METRIC_DROP;
  * mean_flip_rate RISES more than MAX_METRIC_DROP (more flapping is a regression);
  * the candidate covers fewer questions than the baseline (shrinking the suite
    is the oldest way to fake a green run);
  * any question that was STABLE_CORRECT in the baseline is no longer
    STABLE_CORRECT in the candidate. This is the loud, specific one:
    "revenue_completed regressed: stable_correct -> flaky."

The exit code is the contract: 0 releases, 1 blocks. Wire `bedrock gate` into
CI and a reliability regression becomes a failed build, not a customer incident.
"""

from dataclasses import dataclass, field

from . import config, harness


@dataclass
class GateResult:
    passed: bool = True
    reasons: list = field(default_factory=list)
    checked: int = 0

    def fail(self, reason: str) -> None:
        self.passed = False
        self.reasons.append(reason)


def run_gate(baseline: dict, candidate: dict, max_drop: float | None = None) -> GateResult:
    """baseline/candidate are {"metrics": ..., "per_question": ...} dicts."""
    max_drop = config.MAX_METRIC_DROP if max_drop is None else max_drop

    # Validate shape up front: a malformed run must fail loud here, not pass
    # silently (missing metrics used to no-op) or crash with a raw KeyError.
    required = ("n_questions", "trust_rate", "mean_accuracy", "mean_flip_rate")
    for label, payload in (("baseline", baseline), ("candidate", candidate)):
        if "metrics" not in payload or "per_question" not in payload:
            raise ValueError(f"{label} must have 'metrics' and 'per_question'")
        absent = [key for key in required if key not in payload["metrics"]]
        if absent:
            raise ValueError(f"{label} metrics missing keys: {', '.join(absent)}")

    result = GateResult()
    base_m, cand_m = baseline["metrics"], candidate["metrics"]
    base_q, cand_q = baseline["per_question"], candidate["per_question"]

    if cand_m["n_questions"] < base_m["n_questions"]:
        result.fail(
            f"candidate covers {cand_m['n_questions']} questions, "
            f"baseline covered {base_m['n_questions']}"
        )

    _check_drop(result, "trust_rate", base_m.get("trust_rate"), cand_m.get("trust_rate"), max_drop)
    _check_drop(result, "mean_accuracy", base_m.get("mean_accuracy"), cand_m.get("mean_accuracy"), max_drop)
    _check_rise(result, "mean_flip_rate", base_m.get("mean_flip_rate"), cand_m.get("mean_flip_rate"), max_drop)

    for qid, base_stats in base_q.items():
        cand_stats = cand_q.get(qid)
        if cand_stats is None:
            result.fail(f"question '{qid}' is missing from the candidate run")
            continue
        if base_stats["verdict"] == harness.STABLE_CORRECT and cand_stats["verdict"] != harness.STABLE_CORRECT:
            result.fail(
                f"{qid} regressed: stable_correct -> {cand_stats['verdict']} "
                f"(accuracy {base_stats['accuracy']:.0%} -> {cand_stats['accuracy']:.0%}, "
                f"flip-rate {base_stats['flip_rate']:.0%} -> {cand_stats['flip_rate']:.0%})"
            )

    return result


def _check_drop(result, label, base, cand, max_drop):
    if base is None:
        return
    if cand is None:
        result.fail(f"{label}: baseline has {base:.3f}, candidate has no value")
        return
    result.checked += 1
    if base - cand > max_drop:
        result.fail(f"{label} dropped {base:.3f} -> {cand:.3f} (max allowed drop {max_drop:.2f})")


def _check_rise(result, label, base, cand, max_drop):
    if base is None:
        return
    if cand is None:
        result.fail(f"{label}: baseline has {base:.3f}, candidate has no value")
        return
    result.checked += 1
    if cand - base > max_drop:
        result.fail(f"{label} rose {base:.3f} -> {cand:.3f} (max allowed rise {max_drop:.2f})")


def render(result: GateResult) -> str:
    lines = [f"checked {result.checked} metric(s) against the baseline"]
    if result.passed:
        lines.append("GATE PASSED: no reliability metric regressed beyond the threshold")
    else:
        lines.append(f"GATE FAILED: {len(result.reasons)} regression(s)")
        lines += [f"  - {reason}" for reason in result.reasons]
    return "\n".join(lines)
