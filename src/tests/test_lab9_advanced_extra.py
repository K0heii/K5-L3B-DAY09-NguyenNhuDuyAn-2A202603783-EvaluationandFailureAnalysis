"""Extra M5-M7 tests covering hidden anti-gaming traps and ratchet rules."""

from __future__ import annotations

import copy

import pytest

from lab9 import gate
from tests.test_lab9_advanced import ROWS, SPEC, _report

pytestmark = pytest.mark.student


def test_advanced_integrity_flags_duplicate_rows_with_same_total_len():
    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    dup_rows = copy.deepcopy(ROWS[:-1]) + [copy.deepcopy(ROWS[0])]
    pr = _report(dup_rows, {"pass_rate": 1.0})
    assert gate.integrity_check(pr, base, SPEC)


def test_advanced_integrity_flags_evaluator_failures_on_green_run():
    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    pr = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    pr["evaluator_failures"] = ["E-000@1:TrialPass:simulated crash"]
    assert gate.integrity_check(pr, base, SPEC)


def test_advanced_integrity_flags_none_row_and_tampered_summary():
    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    none_rows = copy.deepcopy(ROWS)
    none_rows[0]["pass_rate"] = None
    assert gate.integrity_check(_report(none_rows, {"pass_rate": 1.0}), base, SPEC)

    tampered_rows = copy.deepcopy(ROWS)
    tampered_rows[0]["pass_rate"] = False
    assert gate.integrity_check(_report(tampered_rows, {"pass_rate": 1.0}), base, SPEC)


def test_advanced_integrity_flags_relabelled_slices_and_slice_ratchet():
    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    relabelled = copy.deepcopy(ROWS)
    relabelled[0]["slices"] = []
    assert gate.integrity_check(_report(relabelled, {"pass_rate": 1.0}), base, SPEC)

    strict_spec = copy.deepcopy(SPEC)
    strict_spec["metrics"][0]["threshold"]["no_significant_drop"] = True
    strict_spec["slices"] = [
        {"name": "denial", "metric": "pass_rate", "min": 0.9, "no_significant_drop": True, "blocking": True}
    ]

    dropped_nsd = copy.deepcopy(strict_spec)
    dropped_nsd["metrics"][0]["threshold"].pop("no_significant_drop")
    assert gate.integrity_check(base, base, dropped_nsd, strict_spec)

    dropped_slice = copy.deepcopy(strict_spec)
    dropped_slice["slices"] = []
    assert gate.integrity_check(base, base, dropped_slice, strict_spec)

    non_blocking_slice = copy.deepcopy(strict_spec)
    non_blocking_slice["slices"][0]["blocking"] = False
    assert gate.integrity_check(base, base, non_blocking_slice, strict_spec)
