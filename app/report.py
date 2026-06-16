"""Render the stability scorecard a non-engineer can read in five seconds.

The headline is the line that goes in the README and every proposal:
"11/14 questions correct and identical across 5 runs. 3 FLAP." For each
flapper, we show the distinct results it gave and a sample of the diverging
SQL, so the failure is "your revenue query drops the status filter on some
runs", not just a red number.
"""

from collections import OrderedDict

from . import harness


def render_text(report: harness.StabilityReport) -> str:
    m = report.metrics()
    lines = []
    lines.append("=" * 64)
    lines.append("BEDROCK STABILITY SCORECARD")
    lines.append("=" * 64)
    lines.append(
        f"{m['stable_correct']}/{m['n_questions']} questions answered correctly "
        f"and identically across {m['k']} runs."
    )
    if m["flaky"]:
        lines.append(f"  {m['flaky']} FLAP (a different answer depending on the run)")
    if m["stable_wrong"]:
        lines.append(f"  {m['stable_wrong']} consistently WRONG")
    if m["error"]:
        lines.append(f"  {m['error']} ERROR (no valid query)")
    lines.append("")
    lines.append(
        f"trust rate {m['trust_rate']:.0%}   "
        f"mean accuracy {m['mean_accuracy']:.0%}   "
        f"mean flip-rate {m['mean_flip_rate']:.0%}"
    )

    flappers = [q for q in report.questions if q.verdict == harness.FLAKY]
    wrong = [q for q in report.questions if q.verdict == harness.STABLE_WRONG]
    errored = [q for q in report.questions if q.verdict == harness.ERROR]

    if flappers:
        lines.append("")
        lines.append("-" * 64)
        lines.append("FLAPPING QUESTIONS (the ones a single-run eval would have shipped)")
        lines.append("-" * 64)
        for q in flappers:
            lines += _flapper_block(q)

    for q in wrong:
        lines.append("")
        lines.append(f"[WRONG] {q.id}: {q.question}")
        lines.append(f"  expected: {q.key_preview}")
        lines.append(f"  always returned: {q.runs[0].preview}")

    for q in errored:
        lines.append("")
        lines.append(f"[ERROR] {q.id}: every run failed to produce a valid query")

    lines.append("")
    return "\n".join(lines)


def _flapper_block(q: harness.QuestionReport) -> list:
    lines = []
    lines.append("")
    lines.append(f"* {q.id}: {q.question}")
    lines.append(
        f"  accuracy {q.accuracy:.0%} across {q.k} runs, "
        f"flip-rate {q.flip_rate:.0%}, {q.n_distinct} distinct answers"
    )
    lines.append(f"  answer key: {q.key_preview}")
    # group runs by the answer they produced, preserving first-seen order
    groups = OrderedDict()
    for obs in q.runs:
        groups.setdefault(obs.signature, []).append(obs)
    for sig, obs_list in groups.items():
        first = obs_list[0]
        tag = "MATCHES KEY" if first.matches_key else "WRONG"
        runs = ",".join(str(o.run) for o in obs_list)
        lines.append(f"    [{tag}] {len(obs_list)}/{q.k} runs (runs {runs}): {first.preview}")
        sql = (first.sql or "").replace("\n", " ").strip()
        if len(sql) > 160:
            sql = sql[:157] + "..."
        lines.append(f"      sql: {sql}")
    return lines


def render_markdown(report: harness.StabilityReport) -> str:
    m = report.metrics()
    out = ["# Bedrock stability scorecard", ""]
    out.append(
        f"**{m['stable_correct']}/{m['n_questions']}** questions answered correctly "
        f"and identically across **{m['k']} runs**."
    )
    out.append("")
    out.append(f"- Flapping: **{m['flaky']}**")
    out.append(f"- Consistently wrong: **{m['stable_wrong']}**")
    out.append(f"- Errored: **{m['error']}**")
    out.append(
        f"- Trust rate **{m['trust_rate']:.0%}** | mean accuracy "
        f"{m['mean_accuracy']:.0%} | mean flip-rate {m['mean_flip_rate']:.0%}"
    )
    out.append("")
    out.append("| question | verdict | accuracy | flip-rate | distinct |")
    out.append("|---|---|---|---|---|")
    for q in report.questions:
        out.append(
            f"| {q.id} | {q.verdict} | {q.accuracy:.0%} | "
            f"{q.flip_rate:.0%} | {q.n_distinct} |"
        )
    out.append("")
    return "\n".join(out)
