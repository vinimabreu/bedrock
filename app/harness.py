"""Run each gold question K times and measure stability, not just accuracy.

A normal eval runs once, sees green, and ships something flaky. The harness
runs the REAL agent loop K times per question (replayed offline from a fixture,
or live), executes each generated query against the read-only database, and
scores what a single run cannot show:

  * accuracy  - fraction of the K runs whose result matches the answer key.
  * stability - do the K runs agree with EACH OTHER? A question right 3 of 5
    times reads as 0.6 accurate and is actually FLAKY: it returns a different
    answer depending on the run, which is the production failure a single-run
    eval cannot see. flip_rate = 1 - (runs in the modal result / K).
  * verdict   - STABLE_CORRECT (agrees with itself AND the key), FLAKY (does
    not agree with itself), STABLE_WRONG (agrees with itself but not the key),
    or ERROR (every run failed).

Everything here is deterministic given the runs. The only nondeterminism is the
model's SQL, which is exactly what is being measured.
"""

from collections import Counter
from dataclasses import dataclass, field

from . import agent, config, equivalence, gold as gold_mod
from . import schema as schema_mod

STABLE_CORRECT = "stable_correct"
FLAKY = "flaky"
STABLE_WRONG = "stable_wrong"
ERROR = "error"

_ERROR_SIG = (("__error__",),)  # a distinct signature so failed runs count as disagreement


@dataclass
class RunObs:
    run: int
    ok: bool
    sql: str | None
    signature: tuple
    preview: str
    matches_key: bool
    error: str | None = None


@dataclass
class QuestionReport:
    id: str
    question: str
    k: int
    accuracy: float
    flip_rate: float
    n_distinct: int
    verdict: str
    answer_sql: str
    key_preview: str
    runs: list = field(default_factory=list)

    @property
    def is_flapper(self) -> bool:
        return self.verdict == FLAKY


@dataclass
class StabilityReport:
    k: int
    db_path: str
    questions: list  # list[QuestionReport]

    def metrics(self) -> dict:
        n = len(self.questions)
        if n == 0:
            return {"n_questions": 0, "k": self.k}
        verdicts = Counter(q.verdict for q in self.questions)
        stable_correct = verdicts[STABLE_CORRECT]
        return {
            "n_questions": n,
            "k": self.k,
            "stable_correct": stable_correct,
            "flaky": verdicts[FLAKY],
            "stable_wrong": verdicts[STABLE_WRONG],
            "error": verdicts[ERROR],
            # the headline number: questions you can actually trust in production
            "trust_rate": round(stable_correct / n, 4),
            "mean_accuracy": round(sum(q.accuracy for q in self.questions) / n, 4),
            "mean_flip_rate": round(sum(q.flip_rate for q in self.questions) / n, 4),
        }

    def per_question(self) -> dict:
        return {
            q.id: {
                "verdict": q.verdict,
                "accuracy": q.accuracy,
                "flip_rate": q.flip_rate,
            }
            for q in self.questions
        }


def run_stability(conn, items, llm_factory, k=None, schema_text=None):
    """Score every gold item over k runs.

    llm_factory(question_id, run) -> an object with write_sql/explain (an
    llm.LLM). FixtureLLM.for_run is the offline factory; a live wrapper is the
    online one. The conn is read-only and reused across all runs.
    """
    k = config.K_RUNS if k is None else k
    if k < 1:
        raise ValueError(f"k must be >= 1; got {k}")
    schema_text = schema_mod.describe(conn) if schema_text is None else schema_text

    reports = []
    for item in items:
        key_columns, key_rows = gold_mod.answer_key(conn, item)
        key_sig = equivalence.canonical(key_columns, key_rows)
        key_preview = equivalence.preview(key_columns, key_rows)

        observations = []
        for run in range(k):
            llm = llm_factory(item.id, run)
            result = agent.SqlAgent(conn, schema_text, llm).ask(item.question)
            if result.succeeded:
                sig = equivalence.canonical(result.columns, result.rows)
                observations.append(
                    RunObs(
                        run=run,
                        ok=True,
                        sql=result.sql,
                        signature=sig,
                        preview=equivalence.preview(result.columns, result.rows),
                        matches_key=(sig == key_sig),
                    )
                )
            else:
                observations.append(
                    RunObs(
                        run=run,
                        ok=False,
                        sql=result.sql,
                        signature=_ERROR_SIG,
                        preview="(failed to produce a valid query)",
                        matches_key=False,
                        error=result.answer,
                    )
                )

        reports.append(_score(item, key_sig, key_preview, observations, k))

    return StabilityReport(k=k, db_path=config.DB_PATH, questions=reports)


def _score(item, key_sig, key_preview, observations, k) -> QuestionReport:
    signatures = [obs.signature for obs in observations]
    counts = Counter(signatures)
    modal_sig, modal_count = counts.most_common(1)[0]

    accuracy = sum(1 for sig in signatures if sig == key_sig) / k
    flip_rate = 1 - modal_count / k
    n_distinct = len(counts)

    if n_distinct > 1:
        verdict = FLAKY
    elif modal_sig == _ERROR_SIG:
        verdict = ERROR
    elif modal_sig == key_sig:
        verdict = STABLE_CORRECT
    else:
        verdict = STABLE_WRONG

    return QuestionReport(
        id=item.id,
        question=item.question,
        k=k,
        accuracy=round(accuracy, 4),
        flip_rate=round(flip_rate, 4),
        n_distinct=n_distinct,
        verdict=verdict,
        answer_sql=item.answer_sql,
        key_preview=key_preview,
        runs=observations,
    )
