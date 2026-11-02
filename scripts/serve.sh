#!/usr/bin/env bash
# Launch llama-server for one of the bench models. Only one fits in memory at a time.
# Usage: scripts/serve.sh qwen27|qwen35a3 [extra llama-server args...]
set -euo pipefail
M=${MODELS_DIR:-$HOME/models}
name=${1:?model name}; shift
case "$name" in
  qwen27)
    args=(-m "$M/Qwen3.8-27B-UD-Q5_K_M.gguf" --spec-type draft-mtp -md "$M/mtp-Qwen3.8-27B-Q4_0.gguf")
    ;;
  qwen35a3)
    args=(-m "$M/Qwen3.6-35B-A3B-UD-Q5_K_M.gguf")
    ;;
  *) echo "unknown model $name" >&2; exit 1 ;;
esac
# Qwen-recommended sampling; KV cache at q8_0 (lower reportedly hurts tool calling);
# explicit context so nothing silently truncates; thinking capped server-side.
exec llama-server "${args[@]}" --alias "$name" --host 127.0.0.1 --port "${PORT:-8080}" \
  -c "${CTX:-65536}" -np 1 -fa on -ngl 999 -ctk q8_0 -ctv q8_0 --jinja \
  --temp 0.6 --top-p 0.95 --top-k 20 --presence-penalty 1.0 \
  --reasoning-budget "${REASONING_BUDGET:-8192}" --cache-reuse 256 --metrics "$@"
