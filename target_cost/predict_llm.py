#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import time
from typing import Dict, Any, List

from openai import OpenAI

CONFIG = {
    "providers": [
        {
            "name": "openai",
            "api_key": "",
            "base_url": None,
            "model": "gpt-5",
        },
        {
            "name": "deepseek",
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-reasoner",   #or deepseek-reasoner
        },
    ],
    "temperature": 0,
    "max_retries": 3,
    "sleep_sec": 0.0,
    "max_tokens": 512,
    "include_observed_time_in_prompt": False,
}

PROMPT_TEMPLATE = """You are estimating the standalone execution time of one Ninja build task.

Return STRICT JSON with exactly these keys:
{{
  "predicted_time_ms": <number>,
  "confidence": <number between 0 and 1>,
  "rationale": "<short explanation>"
}}

Project directory:
{project_dir}

Task:
{task_json}

Rules:
1. Estimate standalone task runtime, not full-build wall time.
2. Use command shape, rule, number of inputs, source complexity, and topology features.
3. For compile tasks, consider source size, include count, template count, complexity, and likely frontend cost.
4. For link/archive tasks, consider input count and aggregation cost.
5. For custom/codegen tasks, consider interpreter startup, tool overhead, and I/O intensity.
6. Output JSON only.
"""

def make_client(api_key: str, base_url: str | None) -> OpenAI:
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)

def build_task_payload(task: Dict[str, Any], include_observed_time: bool) -> Dict[str, Any]:
    payload = {
        "primary_output": task.get("primary_output"),
        "rule": task.get("rule"),
        "task_type": task.get("task_type"),
        "inputs": task.get("inputs"),
        "implicit_inputs": task.get("implicit_inputs"),
        "order_only_inputs": task.get("order_only_inputs"),
        "command": task.get("command"),
        "source_features": task.get("source_features"),
        "topo": task.get("topo"),
    }
    if include_observed_time:
        payload["observed_time_ms"] = task.get("observed_time_ms")
    return payload

def parse_json_response(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    elif text.startswith("```"):
        text = text[len("```"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)

def call_model(
    client: OpenAI,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You estimate Ninja build task runtime and return strict JSON only."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
    )
    text = resp.choices[0].message.content.strip()
    return parse_json_response(text)

def safe_call(
    client: OpenAI,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    max_retries: int,
) -> Dict[str, Any]:
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return call_model(client, model, prompt, temperature, max_tokens)
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(attempt)
    raise RuntimeError(f"failed after {max_retries} retries: {last_err}")

def predict_for_provider(
    provider_cfg: Dict[str, Any],
    data: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    out_dir: pathlib.Path,
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    client = make_client(provider_cfg["api_key"], provider_cfg.get("base_url"))
    provider_name = provider_cfg["name"]
    model = provider_cfg["model"]

    results: List[Dict[str, Any]] = []
    out_path = out_dir / f"llm_predictions_{provider_name}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for idx, task in enumerate(tasks, 1):
            payload = build_task_payload(
                task,
                include_observed_time=config["include_observed_time_in_prompt"],
            )
            prompt = PROMPT_TEMPLATE.format(
                project_dir=data.get("project_dir"),
                task_json=json.dumps(payload, ensure_ascii=False, indent=2),
            )

            row = {
                "primary_output": task.get("primary_output"),
                "task_type": task.get("task_type"),
                "provider": provider_name,
                "model": model,
            }

            try:
                pred = safe_call(
                    client=client,
                    model=model,
                    prompt=prompt,
                    temperature=config["temperature"],
                    max_tokens=config["max_tokens"],
                    max_retries=config["max_retries"],
                )
                row["predicted_time_ms"] = float(pred["predicted_time_ms"])
                row["confidence"] = float(pred["confidence"])
                row["rationale"] = str(pred["rationale"])
            except Exception as e:
                row["error"] = str(e)

            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)

            print(f"[{provider_name}] [{idx}/{len(tasks)}] {task.get('primary_output')}")

            if config["sleep_sec"] > 0:
                time.sleep(config["sleep_sec"])

    print(f"[done] {provider_name} -> {out_path}")
    return results

def merge_compare(
    tasks: List[Dict[str, Any]],
    provider_results: Dict[str, List[Dict[str, Any]]],
    out_path: pathlib.Path,
) -> None:
    by_provider = {}
    for provider, rows in provider_results.items():
        by_provider[provider] = {r["primary_output"]: r for r in rows}

    with out_path.open("w", encoding="utf-8") as f:
        for task in tasks:
            key = task.get("primary_output")
            row = {
                "primary_output": key,
                "task_type": task.get("task_type"),
                "observed_time_ms": task.get("observed_time_ms"),
                "openai": by_provider.get("openai", {}).get(key),
                "deepseek": by_provider.get("deepseek", {}).get(key),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[done] compare -> {out_path}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenAI and DeepSeek sequentially for comparison.")
    parser.add_argument("analysis_json", help="Path to ninja_analysis.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    analysis_path = pathlib.Path(args.analysis_json).resolve()
    data = json.loads(analysis_path.read_text(encoding="utf-8"))

    tasks: List[Dict[str, Any]] = data["tasks"]
    if args.limit is not None:
        tasks = tasks[:args.limit]

    out_dir = analysis_path.parent
    provider_results: Dict[str, List[Dict[str, Any]]] = {}

    for provider_cfg in CONFIG["providers"]:
        rows = predict_for_provider(
            provider_cfg=provider_cfg,
            data=data,
            tasks=tasks,
            out_dir=out_dir,
            config=CONFIG,
        )
        provider_results[provider_cfg["name"]] = rows

    merge_compare(
        tasks=tasks,
        provider_results=provider_results,
        out_path=out_dir / "llm_predictions_compare.jsonl",
    )

    return 0

if __name__ == "__main__":
    raise SystemExit(main())