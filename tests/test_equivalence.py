"""Result-set equivalence is the foundation everything else trusts."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import equivalence  # noqa: E402


def test_row_order_does_not_matter():
    a = equivalence.canonical(["x"], [(1,), (2,), (3,)])
    b = equivalence.canonical(["x"], [(3,), (1,), (2,)])
    assert a == b


def test_duplicate_rows_are_a_multiset_not_a_set():
    one = equivalence.canonical(["x"], [(1,), (1,)])
    two = equivalence.canonical(["x"], [(1,)])
    assert one != two  # two identical rows must not collapse to one


def test_float_tolerance_treats_close_numbers_as_equal():
    assert equivalence.equal(["r"], [(1308.13,)], ["r"], [(1308.130001,)])


def test_int_and_float_of_same_value_match():
    assert equivalence.equal(["n"], [(5,)], ["n"], [(5.0,)])


def test_null_is_distinct_from_zero_and_empty():
    assert not equivalence.equal(["v"], [(None,)], ["v"], [(0,)])
    assert not equivalence.equal(["v"], [(None,)], ["v"], [("",)])


def test_different_values_are_not_equal():
    assert not equivalence.equal(["r"], [(2780222.9,)], ["r"], [(1382120.3,)])


def test_canonical_is_hashable_and_deterministic():
    sig = equivalence.canonical(["a", "b"], [(1, "x"), (2, "y")])
    assert hash(sig) == hash(sig)
    # same data, rows reordered -> identical signature
    sig2 = equivalence.canonical(["a", "b"], [(2, "y"), (1, "x")])
    assert sig == sig2


def test_preview_is_short_and_readable():
    text = equivalence.preview(["revenue"], [(2780222.9,)])
    assert "revenue=2780222.9" in text


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
