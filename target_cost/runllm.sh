#!/usr/bin/env bash
set -euo pipefail

# ===== 基本配置 =====
ANALYSIS_JSON="${1:-/path/to/ninja_analysis.json}"
MODEL="gpt-5"
API_KEY="你的key"

# 如果你用 OpenAI 官方接口，留空即可
BASE_URL=""

# 输出文件
OUT_FILE="llm_predictions.jsonl"

# 可选参数
LIMIT=""
SLEEP="0"

# ===== 构造命令 =====
CMD=(
  python3 predict_llm.py
  "$ANALYSIS_JSON"
  --model "$MODEL"
  --api-key "$API_KEY"
  --out "$OUT_FILE"
)

if [[ -n "$BASE_URL" ]]; then
  CMD+=(--base-url "$BASE_URL")
fi

if [[ -n "$LIMIT" ]]; then
  CMD+=(--limit "$LIMIT")
fi

if [[ -n "$SLEEP" ]]; then
  CMD+=(--sleep "$SLEEP")
fi

echo "[RUN] ${CMD[*]}"
"${CMD[@]}"