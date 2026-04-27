#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pathlib
from statistics import median
from typing import Dict, List


def log_normalize(value: float, max_value: float) -> float:
    if max_value <= 0 or value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(max_value)


def fit_medians_by_type(tasks: List[Dict]) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = {}
    for task in tasks:
        t = task.get("task_type", "unknown")
        ms = task.get("observed_time_ms")
        if ms is None:
            continue
        buckets.setdefault(t, []).append(float(ms))
    return {k: median(v) for k, v in buckets.items() if v}


def predict_compile(task: Dict, max_vals: Dict[str, float], base_ms: float) -> float:
    sf = task.get("source_features") or {}
    topo = task.get("topo") or {}

    # Compared with the user's original rule, this extends it in three ways:
    # 1) keeps code-complexity features for compile tasks only,
    # 2) adds include/template/io-sensitive proxies,
    # 3) adds light topo urgency, useful for scheduling.
    features = {
        "loc": sf.get("loc", 0),
        "function_count": sf.get("function_count", 0),
        "avg_function_length": sf.get("avg_function_length", 0),
        "cyclomatic": sf.get("max_cyclomatic_proxy", 0),
        "nesting": sf.get("max_nesting_depth", 0),
        "include_count": sf.get("include_count", 0),
        "template_count": sf.get("template_count", 0),
        "file_size": sf.get("file_size", 0),
        "remaining_hops": topo.get("longest_remaining_hops", 0),
    }

    weights = {
        "loc": 0.14,
        "function_count": 0.10,
        "avg_function_length": 0.10,
        "cyclomatic": 0.18,
        "nesting": 0.08,
        "include_count": 0.14,
        "template_count": 0.14,
        "file_size": 0.07,
        "remaining_hops": 0.05,
    }

    score = 0.0
    for name, value in features.items():
        score += weights[name] * log_normalize(value, max_vals.get(name, 1.0))

    # Map normalized score to a runtime multiplier.
    return round(base_ms * (0.35 + 2.65 * score), 3)


def predict_link(task: Dict, max_vals: Dict[str, float], base_ms: float) -> float:
    topo = task.get("topo") or {}
    explicit_inputs = len(task.get("inputs") or [])
    score = (
        0.55 * log_normalize(explicit_inputs, max_vals.get("link_inputs", 1.0)) +
        0.25 * log_normalize(topo.get("fanin", 0), max_vals.get("fanin", 1.0)) +
        0.20 * log_normalize(topo.get("longest_remaining_hops", 0), max_vals.get("remaining_hops", 1.0))
    )
    return round(base_ms * (0.5 + 3.5 * score), 3)


def predict_archive_or_io(task: Dict, max_vals: Dict[str, float], base_ms: float) -> float:
    explicit_inputs = len(task.get("inputs") or [])
    sf = task.get("source_features") or {}
    score = (
        0.6 * log_normalize(explicit_inputs, max_vals.get("link_inputs", 1.0)) +
        0.4 * log_normalize(sf.get("file_size", 0), max_vals.get("file_size", 1.0))
    )
    return round(base_ms * (0.4 + 2.6 * score), 3)


def compute_max_values(tasks: List[Dict]) -> Dict[str, float]:
    vals = {
        "loc": 0.0,
        "function_count": 0.0,
        "avg_function_length": 0.0,
        "cyclomatic": 0.0,
        "nesting": 0.0,
        "include_count": 0.0,
        "template_count": 0.0,
        "file_size": 0.0,
        "remaining_hops": 0.0,
        "fanin": 0.0,
        "link_inputs": 0.0,
    }
    for task in tasks:
        sf = task.get("source_features") or {}
        topo = task.get("topo") or {}
        vals["loc"] = max(vals["loc"], sf.get("loc", 0))
        vals["function_count"] = max(vals["function_count"], sf.get("function_count", 0))
        vals["avg_function_length"] = max(vals["avg_function_length"], sf.get("avg_function_length", 0))
        vals["cyclomatic"] = max(vals["cyclomatic"], sf.get("max_cyclomatic_proxy", 0))
        vals["nesting"] = max(vals["nesting"], sf.get("max_nesting_depth", 0))
        vals["include_count"] = max(vals["include_count"], sf.get("include_count", 0))
        vals["template_count"] = max(vals["template_count"], sf.get("template_count", 0))
        vals["file_size"] = max(vals["file_size"], sf.get("file_size", 0))
        vals["remaining_hops"] = max(vals["remaining_hops"], topo.get("longest_remaining_hops", 0))
        vals["fanin"] = max(vals["fanin"], topo.get("fanin", 0))
        vals["link_inputs"] = max(vals["link_inputs"], len(task.get("inputs") or []))
    return vals


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict Ninja task durations with a type-aware heuristic.")
    parser.add_argument("analysis_json", help="Output of ninja_analyzer.py")
    parser.add_argument("--out", default="heuristic_predictions.json")
    args = parser.parse_args()

    path = pathlib.Path(args.analysis_json).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    medians = fit_medians_by_type(tasks)
    max_vals = compute_max_values(tasks)

    global_median = median([float(t["observed_time_ms"]) for t in tasks if t.get("observed_time_ms") is not None] or [100.0])

    predictions = []
    for task in tasks:
        ttype = task.get("task_type", "unknown")
        base_ms = medians.get(ttype, global_median)
        if ttype == "compile":
            pred = predict_compile(task, max_vals, base_ms)
        elif ttype == "link":
            pred = predict_link(task, max_vals, base_ms)
        elif ttype in {"archive", "io"}:
            pred = predict_archive_or_io(task, max_vals, base_ms)
        elif ttype == "phony":
            pred = 0.0
        else:
            topo = task.get("topo") or {}
            pred = round(base_ms * (0.7 + 0.3 * log_normalize(topo.get("fanin", 0), max_vals.get("fanin", 1.0))), 3)

        predictions.append({
            "primary_output": task["primary_output"],
            "task_type": ttype,
            "observed_time_ms": task.get("observed_time_ms"),
            "predicted_time_ms": pred,
        })

    out_path = path.parent / args.out
    out_path.write_text(json.dumps({
        "method": "type_aware_heuristic",
        "medians_by_type": medians,
        "predictions": predictions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] predictions={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
