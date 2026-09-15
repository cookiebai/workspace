# B4-Style Traffic Optimizer

This configurator emulates the Google B4 WAN optimizer on top of the OpenSN control API. It collects the live topology from Etcd, enumerates multiple candidate paths between ground stations, and solves a multi-commodity flow linear program to maximize weighted throughput subject to the current link capacities. The resulting allocations are pushed back to Etcd as link parameters so the daemon and UI can visualize target bandwidths and utilization.

## Dependencies

Install the extra Python packages inside the CodeServer workspace (or your local virtualenv):

```bash
pip install networkx pulp
```

The script also reuses helpers under `TopoConfigurators/Standard`, so run it from the repository root to keep relative imports intact.

## Usage

```bash
cd TopoConfigurators/B4
ADDR=<master_ip> PORT=<master_port> [B4_DEMAND_PROFILE=path/to/profile.json] make run
```

The environment variables must match the master `NodeDaemon` HTTP endpoint (e.g., the values from `config/config.json`). Set `B4_DEMAND_PROFILE` to point at an optional JSON file that specifies per-ground-station traffic demands; otherwise the controller will assume a full mesh with a uniform rate.

## Output

- Each solving round writes the planned per-link bandwidth (`B4_TARGET_BPS`) and utilization percentage (`B4_UTIL_PCT`) into the link parameter map so they show up in the monitoring stack.
- Solver statistics (total satisfied demand, dropped flows, etc.) are logged via `loguru`.

You can adapt `GROUND_STATION_BASE_BPS`, `K_PATHS`, or the priority builder inside `main.py` to match your own workload model.

## Demand Profile Format

Optional profile files should look like this:

```json
{
	"default_rate_bps": 50000000,
	"default_priority": 1.0,
	"ground_station_pairs": [
		{"src_index": 0, "dst_index": 5, "rate_bps": 80000000, "priority": 2.0, "bidirectional": true},
		{"src_index": 1, "dst_index": 7, "rate_bps": 40000000, "priority": 0.5, "bidirectional": false}
	]
}
```

- `src_index`/`dst_index` reference the `GroundStationIndex` field inside the topology JSON.
- When `ground_station_pairs` is non-empty, only those flows are instantiated. Otherwise the optimizer falls back to a full-mesh demand matrix using the default rate/priority.
