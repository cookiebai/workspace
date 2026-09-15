#!/usr/bin/env python3
"""B4 vs. baseline throughput benchmark orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.json"
DEFAULT_BASELINE_CMD = ["make", "-C", "TopoConfigurators/Standard", "run"]
DEFAULT_B4_CMD = ["make", "-C", "TopoConfigurators/B4", "run"]
METRIC_FIELDS = {
    "SendBps": "send_bps",
    "RecvBps": "recv_bps",
    "SendDropPps": "send_drop_pps",
    "RecvDropPps": "recv_drop_pps",
}


def load_runtime_config(path: Path) -> Dict:
    with path.open() as fp:
        return json.load(fp)


def infer_master_addr(cfg: Dict, override_addr: Optional[str], override_port: Optional[int]) -> tuple[str, int]:
    addr = override_addr or cfg["app"].get("master_address") or "127.0.0.1"
    port = override_port or cfg["app"].get("listen_port", 8080)
    return str(addr), int(port)


def build_env(base_env: Dict[str, str], addr: str, port: int, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = base_env.copy()
    env.update({"ADDR": addr, "PORT": str(port)})
    if extra:
        env.update(extra)
    return env


def wait_and_collect(query_api: QueryApi, bucket: str, window: int) -> Dict[str, float]:
    snapshot: Dict[str, float] = {}
    for field, label in METRIC_FIELDS.items():
        snapshot[label] = fetch_field_sum(query_api, bucket, field, window)
    return snapshot


def fetch_field_sum(query_api: QueryApi, bucket: str, field: str, window: int) -> float:
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{window}s)
  |> filter(fn: (r) => r._measurement == "link_performance")
  |> filter(fn: (r) => r._field == "{field}")
  |> aggregateWindow(every: {window}s, fn: mean, createEmpty: false)
  |> group(columns: [])
  |> sum()
"""
    tables = query_api.query(flux)
    total = 0.0
    for table in tables:
        for record in table.records:
            value = record.get_value()
            if value is not None:
                total += float(value)
    return total


def aggregate_samples(samples: List[Dict[str, float]]) -> Dict[str, float]:
    if not samples:
        return {label: 0.0 for label in METRIC_FIELDS.values()}
    summary: Dict[str, float] = {}
    for label in METRIC_FIELDS.values():
        values = [sample[label] for sample in samples if label in sample]
        summary[label] = statistics.mean(values) if values else 0.0
    return summary


def terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            proc.send_signal(sig)
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue
    proc.kill()


def run_scenario(
    name: str,
    command: List[str],
    env: Dict[str, str],
    duration: int,
    warmup: int,
    poll_window: int,
    query_api: QueryApi,
    bucket: str,
) -> Dict[str, float]:
    print(f"[+] Starting scenario '{name}' with command: {' '.join(command)}")
    proc = subprocess.Popen(command, env=env, cwd=REPO_ROOT)
    samples: List[Dict[str, float]] = []
    try:
        print(f"    Warmup {warmup}s ...", flush=True)
        time.sleep(warmup)
        start = time.time()
        while time.time() - start < duration:
            sample = wait_and_collect(query_api, bucket, poll_window)
            samples.append(sample)
            time.sleep(poll_window)
    finally:
        terminate_process(proc)
    summary = aggregate_samples(samples)
    print(f"    Completed '{name}': {summary}")
    return summary


def compute_improvement(baseline: Dict[str, float], challenger: Dict[str, float], key: str) -> float:
    base = baseline.get(key, 0.0)
    test = challenger.get(key, 0.0)
    if base <= 0:
        return float("inf") if test > 0 else 0.0
    return ((test - base) / base) * 100.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run B4 against baseline and compare link KPIs via InfluxDB")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config/config.json")
    parser.add_argument("--addr", help="Override master HTTP address")
    parser.add_argument("--port", type=int, help="Override master HTTP port")
    parser.add_argument("--duration", type=int, default=120, help="Sampling duration per scenario (seconds)")
    parser.add_argument("--warmup", type=int, default=30, help="Warmup before sampling begins (seconds)")
    parser.add_argument("--window", type=int, default=10, help="Influx aggregation window and poll interval (seconds)")
    parser.add_argument("--baseline-cmd", nargs="+", help="Command to start baseline controller")
    parser.add_argument("--b4-cmd", nargs="+", help="Command to start B4 controller")
    parser.add_argument("--b4-profile", help="Demand profile passed to the B4 controller")
    parser.add_argument("--output", default="perf_results.json", help="Where to store the final summary")
    args = parser.parse_args()

    cfg = load_runtime_config(Path(args.config))
    addr, port = infer_master_addr(cfg, args.addr, args.port)
    dependency = cfg["dependency"]

    client = InfluxDBClient(
        url=f"http://{dependency['influxdb_addr']}:{dependency['influxdb_port']}",
        token=dependency["influxdb_token"],
        org=dependency["influxdb_org"],
        timeout=30_000,
    )
    query_api = client.query_api()
    bucket = dependency["influxdb_bucket"]

    base_env = os.environ.copy()
    base_env.setdefault("PYTHONUNBUFFERED", "1")
    env_common = build_env(base_env, addr, port)

    baseline_cmd = args.baseline_cmd or DEFAULT_BASELINE_CMD
    b4_cmd = args.b4_cmd or DEFAULT_B4_CMD

    baseline_summary = run_scenario(
        "baseline",
        baseline_cmd,
        env_common,
        args.duration,
        args.warmup,
        args.window,
        query_api,
        bucket,
    )

    b4_env = env_common.copy()
    if args.b4_profile:
        b4_env["B4_DEMAND_PROFILE"] = args.b4_profile
    b4_summary = run_scenario(
        "b4",
        b4_cmd,
        b4_env,
        args.duration,
        args.warmup,
        args.window,
        query_api,
        bucket,
    )

    improvements = {
        label: compute_improvement(baseline_summary, b4_summary, label)
        for label in METRIC_FIELDS.values()
    }

    output = {
        "baseline": baseline_summary,
        "b4": b4_summary,
        "improvements_pct": improvements,
        "settings": {
            "duration": args.duration,
            "warmup": args.warmup,
            "window": args.window,
            "addr": addr,
            "port": port,
            "baseline_cmd": baseline_cmd,
            "b4_cmd": b4_cmd,
            "b4_profile": args.b4_profile,
        },
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    print("\n=== Comparison Summary ===")
    for label in METRIC_FIELDS.values():
        print(
            f"{label}: baseline={baseline_summary[label]:.2f} | b4={b4_summary[label]:.2f} | "
            f"delta={improvements[label]:.2f}%"
        )
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
