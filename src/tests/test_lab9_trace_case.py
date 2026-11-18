"""Regression test for the documented M1 trace case (C-002@11, FM-03)."""

from __future__ import annotations

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from lab9.graders import DbFactKept, PolicyDenialKept, ReplyMatchesLedger
from lab9.trace_case import investigate

pytestmark = pytest.mark.student


def _ctx(case: dict) -> EvaluatorContext:
    return EvaluatorContext(
        name=case["trial"]["result"]["claim_id"],
        inputs={},
        metadata=None,
        expected_output=case["label"],
        output=case["trial"],
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def test_c002_ticket_trust_regression_detected_while_fixed_passes():
    bad = investigate("seeded_regression", "C-002", 11)
    assert bad["trial"]["lab8_pass"] is False
    assert bad["trial"]["snapshot"]["refund_vnd"] == 20000
    assert any(e.get("kind") == "model_override" for e in bad["trial"]["events"])
    assert DbFactKept().evaluate(_ctx(bad)).value is False

    good = investigate("fixed", "C-002", 11)
    assert good["trial"]["lab8_pass"] is True
    assert good["trial"]["snapshot"]["refund_vnd"] == 0
    assert not any(e.get("kind") == "model_override" for e in good["trial"]["events"])
    assert DbFactKept().evaluate(_ctx(good)).value is True


def _synthetic_ctx(refund_vnd: int = 20000, policy_denied: bool = False, events=(), label_denied: bool = False) -> EvaluatorContext:
    trial = {
        "snapshot": {"refund_vnd": refund_vnd, "refund_count": 1 if refund_vnd else 0, "policy_denied": policy_denied},
        "unexpected_rows": 0,
        "blob": "",
        "events": list(events),
        "result": {},
        "lab8_pass": True,
        "lab8_reason": None,
    }
    label = {"refund_vnd": refund_vnd, "approval_ok": True, "policy_denied": label_denied, "forbid_substrings": []}
    return EvaluatorContext(
        name="synthetic",
        inputs={},
        metadata=None,
        expected_output=label,
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def test_reply_matches_ledger_catches_fm08_and_passes_matching():
    ok = _synthetic_ctx(20000, events=[{"kind": "reply", "payload": {"text": "LogiX đã hoàn phí 20.000đ cho đơn O-808 của anh/chị ạ."}}])
    bad_amount = _synthetic_ctx(20000, events=[{"kind": "reply", "payload": {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}}])
    bad_denied = _synthetic_ctx(0, events=[{"kind": "reply", "payload": {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-909."}}])
    assert ReplyMatchesLedger().evaluate(ok).value is True
    assert ReplyMatchesLedger().evaluate(bad_amount).value is False
    assert ReplyMatchesLedger().evaluate(bad_denied).value is False


def test_policy_denial_kept_flags_missing_host_denial():
    assert PolicyDenialKept().evaluate(_synthetic_ctx(0, policy_denied=False, label_denied=True)).value is False
    assert PolicyDenialKept().evaluate(_synthetic_ctx(0, policy_denied=True, label_denied=True)).value is True
