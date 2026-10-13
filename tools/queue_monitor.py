#!/usr/bin/env python3
import logging
import os
import re
import subprocess
import time
from collections import defaultdict

import redis


POLL_INTERVAL_SECONDS = float(os.getenv("QUEUE_MONITOR_INTERVAL_SECONDS", "1"))
DROP_PENALTY_BYTES = int(os.getenv("QUEUE_DROP_PENALTY_BYTES", "1500"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

r = redis.Redis(
    host=os.getenv("TE_REDIS_HOST", "127.0.0.1"),
    port=int(os.getenv("TE_REDIS_PORT", "6379")),
    decode_responses=True,
    socket_timeout=3.0,
)

_last_dropped = {}


def read_host_qdiscs():
    """Read real OpenSN netem/TBF queues from the host, not noqueue in containers."""
    result = subprocess.run(
        ["tc", "-s", "qdisc", "show"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tc qdisc failed")

    stats = defaultdict(lambda: {"backlog": 0, "dropped": 0})
    current_iface = None
    for line in result.stdout.splitlines():
        qdisc_match = re.search(r"^qdisc\s+\S+\s+\S+:\s+dev\s+(\S+)", line)
        if qdisc_match:
            current_iface = qdisc_match.group(1)
            continue
        if not current_iface:
            continue

        backlog_match = re.search(r"\bbacklog\s+(\d+)[bB]\b", line)
        if backlog_match:
            stats[current_iface]["backlog"] = max(
                stats[current_iface]["backlog"],
                int(backlog_match.group(1)),
            )

        dropped_match = re.search(r"\bdropped\s+(\d+)\b", line)
        if dropped_match:
            stats[current_iface]["dropped"] = max(
                stats[current_iface]["dropped"],
                int(dropped_match.group(1)),
            )
    return stats


def collect_queues():
    qdisc_stats = read_host_qdiscs()
    telemetry = defaultdict(dict)
    congested = 0

    for key in r.scan_iter("topo:link:*"):
        link = r.hgetall(key)
        if not link or link.get("status", "UP") != "UP":
            continue
        src = link.get("src")
        local_iface = link.get("local_iface")
        host_iface = link.get("host_iface")
        if not src or not local_iface or not host_iface:
            continue

        current = qdisc_stats.get(host_iface, {"backlog": 0, "dropped": 0})
        dropped = current["dropped"]
        dropped_delta = max(0, dropped - _last_dropped.get(host_iface, dropped))
        _last_dropped[host_iface] = dropped

        # Backlog is the primary Lyapunov queue. Recent actual drops add a
        # short-lived congestion penalty when a full queue drains between polls.
        queue_score = current["backlog"] + dropped_delta * DROP_PENALTY_BYTES
        telemetry[src][local_iface] = queue_score
        if queue_score > 0:
            congested += 1

    pipe = r.pipeline(transaction=True)
    old_keys = list(r.scan_iter("telemetry:queue:*"))
    for key in old_keys:
        pipe.delete(key)
    for node, queues in telemetry.items():
        key = f"telemetry:queue:{node}"
        pipe.hset(key, mapping=queues)
        pipe.expire(key, max(5, int(POLL_INTERVAL_SECONDS * 5)))
    pipe.set("telemetry:queue:last_update_unix", f"{time.time():.6f}")
    pipe.execute()

    logging.info(
        "host qdisc telemetry: nodes=%d links=%d congested=%d",
        len(telemetry),
        sum(len(queues) for queues in telemetry.values()),
        congested,
    )


if __name__ == "__main__":
    r.ping()
    logging.info("OpenSN host queue monitor started")
    while True:
        started = time.monotonic()
        try:
            collect_queues()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logging.error("queue collection failed: %s", exc)
        elapsed = time.monotonic() - started
        time.sleep(max(0.2, POLL_INTERVAL_SECONDS - elapsed))
