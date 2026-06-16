"""Central settings. No secrets in code: the API key comes from the environment.

One source of truth for the whole package. The first block carries the exact
names the vendored agent/llm/db modules expect (so they run unchanged); the
second block is Bedrock's own stability-harness settings.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# --- settings the vendored agent.py / llm.py / db.py expect (do not rename) ---
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_RETRIES = int(os.environ.get("BEDROCK_MAX_RETRIES", "3"))
MAX_ROWS = int(os.environ.get("BEDROCK_MAX_ROWS", "1000"))
QUERY_TIMEOUT_S = float(os.environ.get("BEDROCK_QUERY_TIMEOUT_S", "5.0"))

# --- Bedrock stability harness ---
DB_PATH = os.environ.get("BEDROCK_DB", str(DATA / "store.db"))
GOLD_PATH = os.environ.get("BEDROCK_GOLD", str(DATA / "gold.json"))
FIXTURE_PATH = os.environ.get("BEDROCK_FIXTURE", str(DATA / "fixture.jsonl"))
BASELINE_PATH = os.environ.get("BEDROCK_BASELINE", str(DATA / "baseline.json"))

# How many times each question is run to measure non-determinism.
K_RUNS = int(os.environ.get("BEDROCK_K", "5"))
# Decimals to round numeric cells to before comparing result sets.
FLOAT_TOLERANCE = int(os.environ.get("BEDROCK_FLOAT_TOL", "2"))
# Gate: the largest drop in a "higher is better" metric (or rise in flip-rate)
# allowed before a candidate is blocked from replacing the baseline.
MAX_METRIC_DROP = float(os.environ.get("BEDROCK_MAX_DROP", "0.05"))
