#!/usr/bin/env bash
# Layer 2 of the privacy proof on Linux: trace every connect/sendto/sendmsg
# system call made by the LegalLens process (and its threads) during a full
# analysis, then list any destination that is not loopback or a Unix socket.
# Run llama-server under `strace -f -e trace=network -p <pid>` the same way to
# cover it too.
#
#   ./privacy/monitor.sh            # needs strace
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${FILE:-data/samples/privacy_canary.txt}"
CANARY="${CANARY:-QZX-CANARY-41907}"
OUT="${OUT:-docs/examples/privacy/run-monitored-linux}"
mkdir -p "$OUT"
export GEMMA_TIMEOUT=900

strace -f -qq -e trace=connect,sendto,sendmsg -o "$OUT/strace.txt" \
  python3 -m privacy.capture --file "$FILE" --out "$OUT" --mode block --canary "$CANARY" \
  | tee "$OUT/capture_stdout.txt"

# inet/inet6 destinations that are not loopback
grep -E 'sin6?_addr' "$OUT/strace.txt" \
  | grep -vE 'inet_addr\("127\.|inet_pton\(AF_INET6, "::1"' > "$OUT/non_loopback.txt" || true
n=$(wc -l < "$OUT/non_loopback.txt")
echo "strace: $(wc -l < "$OUT/strace.txt") network syscalls, $n to non-loopback addresses"
[ "$n" -eq 0 ] && echo "overall: PASS" || { echo "overall: FAIL (see $OUT/non_loopback.txt)"; exit 1; }
