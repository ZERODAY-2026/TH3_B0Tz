#!/usr/bin/env bash
# Layer 1 of the privacy proof on Linux: run llama-server and the full
# analysis inside a fresh network namespace that has only a loopback
# interface, so nothing in it can reach any network. Needs unprivileged user
# namespaces (most distros; WSL2 works). No root required.
#
#   MODEL=models/gemma-4-E4B-it-Q4_K_M.gguf ./privacy/run_offline.sh
#
# Docker alternative (same idea):
#   docker run --rm --network none -v "$PWD":/work -w /work <image-with-python-and-llama.cpp> ./privacy/run_offline.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export MODEL="${MODEL:-models/gemma-4-E4B-it-Q4_K_M.gguf}"
export FILE="${FILE:-data/samples/privacy_canary.txt}"
export CANARY="${CANARY:-QZX-CANARY-41907}"
export OUT="${OUT:-docs/examples/privacy/run-offline-linux}"
export LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
export GEMMA_TIMEOUT=900
mkdir -p "$OUT"

exec unshare --user --map-root-user --net bash -c '
  set -euo pipefail
  ip link set lo up
  { echo "# interfaces inside the namespace"; ip -o addr; echo; echo "# routes"; ip route; ip -6 route; } > "$OUT/netns_state.txt" 2>&1
  "$LLAMA_SERVER" -m "$MODEL" --host 127.0.0.1 --port 8080 -c 8192 --jinja \
      --chat-template-kwargs "{\"enable_thinking\":false}" > "$OUT/llama-server.log" 2>&1 &
  server=$!
  trap "kill $server 2>/dev/null || true" EXIT
  for _ in $(seq 1 120); do
    python3 -c "import urllib.request,sys; urllib.request.urlopen(\"http://127.0.0.1:8080/health\", timeout=2)" 2>/dev/null && break
    sleep 1
  done
  python3 -m privacy.capture --file "$FILE" --out "$OUT" --mode block \
      --canary "$CANARY" --server-log "$OUT/llama-server.log"
'
