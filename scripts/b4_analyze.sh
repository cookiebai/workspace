#!/usr/bin/env bash
# Quick B4 effectiveness snapshot for the last N seconds (default 600)
# Usage: ./scripts/b4_analyze.sh [window_seconds]

set -euo pipefail
WINDOW="${1:-600}"
LOG_B4="/tmp/b4.log"
API_LINK="http://192.168.1.129:8080/api/link/"

python3 - "$WINDOW" "$LOG_B4" <<'PY'
import sys, re, statistics, datetime as dt, os
window=int(sys.argv[1]); log=sys.argv[2]
now=dt.datetime.now()
sats=[]; unmet=[]
pat=re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*satisfied ([0-9.]+).*unmet ([0-9.]+)')
if os.path.exists(log):
    with open(log) as f:
        for line in f:
            m=pat.search(line)
            if not m: continue
            ts=dt.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f')
            if (now - ts).total_seconds() <= window:
                sats.append(float(m.group(2)))
                unmet.append(float(m.group(3)))

def summary(name, arr):
    if not arr:
        return f"{name}: no data in last {window}s"
    p95 = statistics.quantiles(arr, n=100)[94] if len(arr) >= 20 else None
    p95_txt = f" p95={p95:.3f}" if p95 is not None else ""
    return f"{name}: count={len(arr)} avg={statistics.mean(arr):.3f} p50={statistics.median(arr):.3f}{p95_txt} max={max(arr):.3f}"

print(f"Window(s): {window}")
print(summary('satisfied_Gbps', sats))
print(summary('unmet_Gbps', unmet))
PY

# Link enablement quick check
if command -v curl >/dev/null; then
  tmp_links=$(mktemp)
  if curl -s "$API_LINK" -o "$tmp_links"; then
    python3 - "$tmp_links" <<'PY'
import sys, json
p=sys.argv[1]
data=json.load(open(p))
links=data.get('data', [])
dis=[l for l in links if not l.get('enable')]
bad=[l for l in links if not l.get('link_id') or l.get('link_id')=='']
print(f"links={len(links)} disabled={len(dis)} empty_id={len(bad)}")
print("sample_disabled", [l.get('link_id') for l in dis[:5]])
PY
  else
    echo "Failed to fetch link API" >&2
  fi
  rm -f "$tmp_links"
else
  echo "curl not found; skip link check" >&2
fi
