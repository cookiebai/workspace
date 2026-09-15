#!/usr/bin/env bash
# Compare throughput with B4 off vs on by running iperf3 between two endpoints.
# You must supply how to run iperf3 server/client (e.g., ssh to nodes or run locally in netns).
# Minimal usage example (same host namespaces):
#   SERVER_CMD="ip netns exec ns-server" CLIENT_CMD="ip netns exec ns-client" \
#   SERVER_IP=10.0.0.1 CLIENT_IP=10.0.0.2 ./scripts/b4_compare_iperf.sh
# Common args:
#   SERVER_CMD: prefix to run iperf3 on server side (default: "")
#   CLIENT_CMD: prefix to run iperf3 on client side (default: "")
#   SERVER_IP:  iperf3 -s bind address (required)
#   CLIENT_IP:  iperf3 client connect address (required)
#   DURATION:   iperf3 -t seconds (default 60)
#   PARALLEL:   iperf3 -P (default 8)
#   RESET=1:    also do emulation stop/reset/start for a clean run (default 0)
#
# Flow:
#   1) Stop B4 (and optionally stop/reset/start emulation).
#   2) Ensure Standard running (best-effort).
#   3) Run iperf3 baseline (B4 off).
#   4) Start B4, wait 10s.
#   5) Run iperf3 with B4 on.
#   6) Print side-by-side Mbps results.

set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
B4_CMD="TopoConfigurators/B4/main.py"
STD_CMD="TopoConfigurators/Standard/main.py"
ADDR=${ADDR:-192.168.1.129}
PORT=${PORT:-8080}
SERVER_CMD=${SERVER_CMD:-}
CLIENT_CMD=${CLIENT_CMD:-}
SERVER_IP=${SERVER_IP:-}
CLIENT_IP=${CLIENT_IP:-}
DURATION=${DURATION:-60}
PARALLEL=${PARALLEL:-8}
RESET=${RESET:-0}

if [[ -z "$SERVER_IP" || -z "$CLIENT_IP" ]]; then
  echo "SERVER_IP and CLIENT_IP are required" >&2
  exit 1
fi

run_iperf() {
  local label=$1
  echo "[iperf][$label] starting server..."
  $SERVER_CMD iperf3 -s -1 -B "$SERVER_IP" >/tmp/iperf_server_$label.log 2>&1 &
  local srv_pid=$!
  sleep 1
  echo "[iperf][$label] running client..."
  $CLIENT_CMD iperf3 -c "$SERVER_IP" -t "$DURATION" -P "$PARALLEL" -f m \
    >/tmp/iperf_client_$label.log 2>&1 || true
  wait $srv_pid || true
  echo "[iperf][$label] result (client):"
  tail -n 5 /tmp/iperf_client_$label.log | sed "s/^/[iperf][$label] /"
}

stop_b4() {
  pkill -f "$B4_CMD" >/dev/null 2>&1 || true
}
start_b4() {
  cd "$ROOT_DIR"
  nohup env PYTHONPATH=$ROOT_DIR/TopoConfigurators ADDR=$ADDR PORT=$PORT \
    python3 -u $B4_CMD > /tmp/b4.log 2>&1 &
  echo $! > /tmp/b4.pid
}
ensure_standard() {
  if pgrep -f "$STD_CMD" >/dev/null; then return; fi
  cd "$ROOT_DIR"
  nohup env PYTHONPATH=$ROOT_DIR/TopoConfigurators ADDR=$ADDR PORT=$PORT \
    python3 -u $STD_CMD > /tmp/standard.log 2>&1 &
  echo $! > /tmp/standard.pid
}
reset_emulation() {
  cd "$ROOT_DIR"
  curl -s -X POST http://$ADDR:$PORT/api/emulation/stop >/dev/null
  curl -s -X POST http://$ADDR:$PORT/api/emulation/reset >/dev/null
  curl -s -X POST http://$ADDR:$PORT/api/emulation/update \
    -H 'Content-Type: application/json' --data-binary @example/test_topologies/emu_config.json >/dev/null
  curl -s -X POST http://$ADDR:$PORT/api/emulation/topology \
    -H 'Content-Type: application/json' --data-binary @example/test_topologies/topology_config_6_11.json >/dev/null
  curl -s -X POST http://$ADDR:$PORT/api/emulation/start >/dev/null
}

main() {
  echo "=== Phase A: B4 OFF ==="
  stop_b4
  if [[ "$RESET" == "1" ]]; then
    echo "[reset] stop/reset/start emulation"
    reset_emulation
  fi
  ensure_standard
  sleep 5
  run_iperf off

  echo "=== Phase B: B4 ON ==="
  start_b4
  sleep 10
  run_iperf on

  echo "=== Summary (last lines) ==="
  echo "-- off --"; tail -n 5 /tmp/iperf_client_off.log || true
  echo "-- on  --"; tail -n 5 /tmp/iperf_client_on.log || true
}

main "$@"
