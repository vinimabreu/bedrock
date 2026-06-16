"""Result-SET equivalence: do two queries return the same answer?

The whole project rests on comparing the agent's result to a defended answer
key, run after run. Two results are "the same" when they contain the same rows
after canonicalization, regardless of row ORDER. We deliberately do NOT try to
prove two SQL strings equivalent in the abstract (undecidable in general, and a
scope trap): we execute both and compare the result SETS.

Canonicalization policy, written down once:
  * numbers are rounded to FLOAT_TOLERANCE decimals before comparison, so
    1308.13 == 1308.130001 and an integer 5 equals a float 5.0. This is
    fixed-precision quantization, not an absolute tolerance band: two values
    that straddle a rounding boundary still differ.
  * NULL stays a distinct value (None), never coerced to 0 or "". NaN is tagged
    so two identical NaN results compare equal instead of falsely flapping.
  * booleans are tagged so they never collide with a numeric 0 or 1.
  * everything else compares as its trimmed string form.
  * rows compare as a MULTISET, so a missing ORDER BY never causes a false
    mismatch.

Two things this v1 deliberately does NOT do (stated so the scope is honest, not
hidden): it compares cell VALUES positionally and does NOT verify column NAMES,
so a query returning the same numbers under a different column label is treated
as equal (the answer key defines the expected values, and the agent is free to
alias columns its own way). And equivalence is only defined below the MAX_ROWS
cap: an answer key whose result exceeds the cap is rejected loudly in
gold.answer_key rather than compared against a truncated set. Column-name- and
column-order-aware comparison is on the roadmap.

The canonical form is a hashable, deterministically-ordered tuple, so it drops
straight into a Counter/set when the harness measures self-agreement.
"""

from collections import Counter

from . import config


def _cell(value, tol):
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is an int subclass (1 == True in Python), so tag it: a boolean
        # can then never collide with a numeric 0 or 1 in the signature.
        return ("__bool__", value)
    if isinstance(value, (int, float)):
        # NaN != NaN, so two identical NaN results would falsely flap; tag it.
        if isinstance(value, float) and value != value:
            return "__nan__"
        return round(float(value), tol)
    return str(value).strip()


def canonical(columns, rows, tol=None):
    """A canonical, order-independent signature of a result set."""
    tol = config.FLOAT_TOLERANCE if tol is None else tol
    # `columns` is intentionally NOT part of the signature: the agent may alias
    # columns differently from the answer key, so equality is over VALUES only
    # (positional, per the scope note in the module docstring).
    canon_rows = [tuple(_cell(v, tol) for v in row) for row in rows]
    counter = Counter(canon_rows)
    # Sort by repr so the signature is deterministic regardless of input order.
    return tuple(sorted(counter.items(), key=lambda kv: repr(kv[0])))


def equal(a_columns, a_rows, b_columns, b_rows, tol=None):
    """True when two result sets are equal after canonicalization."""
    return canonical(a_columns, a_rows, tol) == canonical(b_columns, b_rows, tol)


def preview(columns, rows, max_rows=3):
    """A short, human-readable rendering of a result set for reports."""
    if not columns:
        return "(no columns)"
    if not rows:
        return "(0 rows)"
    shown = []
    for row in rows[:max_rows]:
        pairs = ", ".join(
            f"{c}={'NULL' if v is None else v}" for c, v in zip(columns, row)
        )
        shown.append(pairs)
    out = " | ".join(shown)
    if len(rows) > max_rows:
        out += f" | ... ({len(rows) - max_rows} more rows)"
    return out
