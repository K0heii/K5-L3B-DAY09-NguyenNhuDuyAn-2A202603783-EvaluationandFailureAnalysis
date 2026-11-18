"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _is_nonfinite_number(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return not math.isfinite(float(val))
    if isinstance(val, str):
        try:
            return not math.isfinite(float(val))
        except ValueError:
            return True
    return False


def _check_threshold_ratchet(
    label: str, base_cfg: dict[str, Any], pr_cfg: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    if base_cfg.get("blocking") and not pr_cfg.get("blocking"):
        problems.append(f"ratchet: {label} became non-blocking")
    for key in ("min",):
        if key in base_cfg:
            if key not in pr_cfg or pr_cfg[key] < base_cfg[key]:
                problems.append(f"ratchet: {label} lowered or dropped {key}")
    for key in ("max", "max_increase"):
        if key in base_cfg:
            if key not in pr_cfg or pr_cfg[key] > base_cfg[key]:
                problems.append(f"ratchet: {label} raised or dropped {key}")
    if base_cfg.get("no_significant_drop") and not pr_cfg.get("no_significant_drop"):
        problems.append(f"ratchet: {label} dropped no_significant_drop")
    return problems


def _check_ratchet(spec: dict[str, Any], base_spec: dict[str, Any]) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems: list[str] = []
    base_metrics = {m["id"]: m for m in base_spec.get("metrics") or []}
    pr_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for mid, bm in base_metrics.items():
        if mid not in pr_metrics:
            problems.append(f"ratchet: metric {mid} removed")
            continue
        pm = pr_metrics[mid]
        b_th = {**bm.get("threshold", {}), "blocking": bm.get("blocking")}
        p_th = {**pm.get("threshold", {}), "blocking": pm.get("blocking")}
        problems.extend(_check_threshold_ratchet(f"metric {mid}", b_th, p_th))

    base_slices = {(s["name"], s["metric"]): s for s in base_spec.get("slices") or []}
    pr_slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for key, bs_item in base_slices.items():
        name, mid = key
        if key not in pr_slices:
            problems.append(f"ratchet: slice {name}/{mid} removed")
            continue
        problems.extend(_check_threshold_ratchet(f"slice {name}/{mid}", bs_item, pr_slices[key]))

    base_seeds = set(base_spec.get("seeds") or [])
    pr_seeds = set(spec.get("seeds") or [])
    if base_seeds and (base_seeds - pr_seeds):
        problems.append(f"ratchet: dropped seeds {sorted(base_seeds - pr_seeds)}")
    return problems


def _check_row_metrics(pr: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    rows = pr.get("rows") or []
    pr_metrics = pr.get("metrics") or {}
    graded_ids = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for mid in graded_ids:
        bad_rows = [
            r for r in rows
            if mid not in r or r[mid] is None or _is_nonfinite_number(r[mid])
        ]
        if bad_rows:
            problems.append(f"row(s) missing or non-finite for graded metric {mid}")
            continue
        if rows and mid in pr_metrics and isinstance(pr_metrics[mid], (int, float)) and not isinstance(pr_metrics[mid], bool):
            val = float(pr_metrics[mid])
            if math.isfinite(val):
                expected = (
                    sum(bool(r[mid]) for r in rows)
                    if mid in ("secret_leak", "approval_bypass")
                    else round(sum(bool(r[mid]) for r in rows) / len(rows), 4)
                )
                if abs(val - expected) > 1e-3:
                    problems.append(f"metric {mid}={val} disagrees with rows ({expected})")

    if rows and all(r.get("pass_rate") is not None and not _is_nonfinite_number(r.get("pass_rate")) for r in rows):
        by_item: dict[Any, list[bool]] = {}
        for r in rows:
            by_item.setdefault(r.get("item_id"), []).append(bool(r.get("pass_rate")))
        if "pass_5" in pr_metrics and pr_metrics["pass_5"] is not None and not _is_nonfinite_number(pr_metrics["pass_5"]):
            exp_p5 = round(sum(all(v) for v in by_item.values()) / len(by_item), 4)
            if abs(float(pr_metrics["pass_5"]) - exp_p5) > 1e-3:
                problems.append(f"metric pass_5={pr_metrics['pass_5']} disagrees with rows ({exp_p5})")
        for k in spec.get("pass_k") or []:
            if by_item and min(len(v) for v in by_item.values()) >= k:
                for prefix, fn in (("pass_at", stats.pass_at_k), ("pass_hat", stats.pass_hat_k)):
                    key = f"{prefix}_{k}"
                    if key in pr_metrics and pr_metrics[key] is not None and not _is_nonfinite_number(pr_metrics[key]):
                        exp_k = round(sum(fn(len(v), sum(v), k) for v in by_item.values()) / len(by_item), 4)
                        if abs(float(pr_metrics[key]) - exp_k) > 1e-3:
                            problems.append(f"metric {key}={pr_metrics[key]} disagrees with rows ({exp_k})")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    pr_metrics = pr.get("metrics") or {}
    for mid, val in pr_metrics.items():
        if _is_nonfinite_number(val):
            problems.append(f"non-finite metric {mid}={val!r}")
    for m in spec.get("metrics") or []:
        mid = m["id"]
        if mid in GRADERS and pr_metrics.get(mid) is None:
            problems.append(f"missing metric {mid}")

    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty ({len(pr['evaluator_failures'])})")

    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    pr_manifest = pr.get("manifest") or {}
    m_items = int(pr_manifest.get("items") or 0)
    m_seeds = list(pr_manifest.get("seeds") or [])
    if len(set(m_seeds)) != len(m_seeds):
        problems.append("duplicate seeds in manifest")
    if m_items <= 0 or not m_seeds or len(pr_rows) != m_items * len(m_seeds):
        problems.append(f"row count {len(pr_rows)} != manifest {m_items} x {len(m_seeds)}")
    if spec.get("seeds") and set(m_seeds) != set(spec["seeds"]):
        problems.append("manifest seeds differ from spec seeds")

    pr_keys = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    if len(pr_keys) != len(set(pr_keys)):
        problems.append("duplicate (item_id, seed) rows")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(pr_keys) != base_keys or len(pr_rows) != len(base_rows):
        problems.append("(item_id, seed) set differs from baseline")

    problems.extend(_check_row_metrics(pr, spec))

    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    seen_slices: dict[Any, list[str]] = {}
    bad_slice_items: set[str] = set()
    for r in pr_rows:
        iid = r.get("item_id")
        tags = sorted(r.get("slices") or [])
        if iid in base_slices and tags != base_slices[iid]:
            bad_slice_items.add(str(iid))
        if iid in seen_slices and tags != seen_slices[iid]:
            bad_slice_items.add(str(iid))
        seen_slices[iid] = tags
    if bad_slice_items:
        problems.append(f"slice tags modified for {sorted(bad_slice_items)}")

    if base_spec is not None:
        problems.extend(_check_ratchet(spec, base_spec))

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, mid = sl["name"], sl["metric"]
        sid = f"slice:{name}/{mid}"
        a = per_item(pr, mid, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        else:
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                b = per_item(base, mid, slice_name=name)
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap(
                        [a[k] for k in keys],
                        [b[k] for k in keys],
                        n_resamples=bs.get("n_resamples", 1000),
                        rng=bs.get("rng", 2027),
                        confidence=bs.get("confidence", 0.95),
                    )
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict = "missing"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys],
                    [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
            else:
                verdict = "missing"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
