"""Bedrock command line.

  python main.py report                 stability scorecard (offline, no key)
  python main.py report --markdown docs/scorecard.md
  python main.py baseline               save the current run as the baseline
  python main.py gate                   block if the candidate regresses (exit 1)
  python main.py gate --candidate data/fixture_candidate.jsonl
  python main.py record --fixture data/fixture.jsonl   re-record from a live model (needs ANTHROPIC_API_KEY)

The offline commands replay a committed fixture, so they run with no API key and
reproduce to the row. --live runs the real Claude agent instead.
"""

import argparse
import json
import sys

from app import config, db, fixture as fixture_mod, gate as gate_mod
from app import gold as gold_mod, harness, report as report_mod
from app import schema as schema_mod


def _live_factory():
    from app.llm import ClaudeLLM

    shared = ClaudeLLM()  # one client; each run is a fresh, nondeterministic call

    def factory(question_id, run):
        return shared

    return factory


def _build_report(args, fixture_path=None):
    conn = db.connect(config.DB_PATH)
    items = gold_mod.load()
    schema_text = schema_mod.describe(conn)
    k = getattr(args, "k", None) or config.K_RUNS
    if getattr(args, "live", False):
        factory = _live_factory()
    else:
        path = fixture_path or getattr(args, "fixture", None) or config.FIXTURE_PATH
        fx = fixture_mod.FixtureLLM.from_jsonl(path)
        gaps = fx.missing([item.id for item in items], k)
        if gaps:
            shown = ", ".join(f"{qid}#{run}" for qid, run in gaps[:8])
            extra = "" if len(gaps) <= 8 else f" (+{len(gaps) - 8} more)"
            raise SystemExit(
                f"fixture {path} is missing {len(gaps)} run(s) for k={k}: "
                f"{shown}{extra}. Regenerate it: python data/generate_fixture.py"
            )
        factory = fx.for_run
    return harness.run_stability(conn, items, factory, k=k, schema_text=schema_text)


def cmd_report(args):
    rep = _build_report(args)
    print(report_mod.render_text(rep))
    if getattr(args, "markdown", None):
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(report_mod.render_markdown(rep))
        print(f"(markdown written to {args.markdown})")
    return 0


def cmd_baseline(args):
    rep = _build_report(args)
    payload = {"metrics": rep.metrics(), "per_question": rep.per_question()}
    with open(config.BASELINE_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(report_mod.render_text(rep))
    print(f"\nbaseline saved to {config.BASELINE_PATH}")
    return 0


def cmd_gate(args):
    candidate_path = args.candidate or config.FIXTURE_PATH
    rep = _build_report(args, fixture_path=candidate_path)
    candidate = {"metrics": rep.metrics(), "per_question": rep.per_question()}
    with open(config.BASELINE_PATH, encoding="utf-8") as handle:
        baseline = json.load(handle)
    result = gate_mod.run_gate(baseline, candidate)
    print(report_mod.render_text(rep))
    print()
    print(gate_mod.render(result))
    return 0 if result.passed else 1


def cmd_record(args):
    from app.llm import ClaudeLLM

    path = args.fixture or config.FIXTURE_PATH
    fixture_mod.reset(path)
    conn = db.connect(config.DB_PATH)
    items = gold_mod.load()
    schema_text = schema_mod.describe(conn)
    recorder = fixture_mod.RecordingLLM(ClaudeLLM(), path)
    rep = harness.run_stability(conn, items, recorder.for_run, k=args.k or config.K_RUNS, schema_text=schema_text)
    print(report_mod.render_text(rep))
    print(f"\nrecorded live fixture to {path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bedrock", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="print the stability scorecard")
    p_report.add_argument("--live", action="store_true", help="run the real Claude agent (needs a key)")
    p_report.add_argument("--fixture", help="fixture JSONL to replay (offline)")
    p_report.add_argument("--k", type=int, help="runs per question")
    p_report.add_argument("--markdown", help="also write a markdown scorecard here")
    p_report.set_defaults(func=cmd_report)

    p_base = sub.add_parser("baseline", help="save the current run as the baseline")
    p_base.add_argument("--live", action="store_true")
    p_base.add_argument("--fixture")
    p_base.add_argument("--k", type=int)
    p_base.set_defaults(func=cmd_baseline)

    p_gate = sub.add_parser("gate", help="block (exit 1) if the candidate regresses vs baseline")
    p_gate.add_argument("--candidate", help="candidate fixture JSONL")
    p_gate.add_argument("--live", action="store_true")
    p_gate.add_argument("--k", type=int)
    p_gate.set_defaults(func=cmd_gate)

    p_rec = sub.add_parser("record", help="re-record a fixture from a live model")
    p_rec.add_argument("--fixture", help="output fixture path")
    p_rec.add_argument("--k", type=int)
    p_rec.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
