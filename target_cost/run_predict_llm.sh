#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env file not found."
  echo "Please create .env with OPENAI_API_KEY and DEEPSEEK_API_KEY."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Error: OPENAI_API_KEY is not set."
  exit 1
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "Warning: DEEPSEEK_API_KEY is not set. DeepSeek provider may be skipped or fail."
fi

python target_cost/predict_llm.py