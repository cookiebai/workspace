from __future__ import annotations

import itertools
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import networkx as nx
except ImportError as exc:  # pragma: no cover - dependency guard
    raise RuntimeError("networkx is required: pip install networkx") from exc

try:
    from pulp import (  # type: ignore
        LpMaximize,
        LpProblem,
        LpStatusOptimal,
        LpVariable,
        PULP_CBC_CMD,
        lpSum,
    )
except ImportError as exc:  # pragma: no cover - dependency guard
    raise RuntimeError("pulp is required: pip install pulp") from exc

from loguru import logger

from opensn.const.dict_fields import PARAMETER_KEY_BANDWIDTH, PARAMETER_KEY_DELAY
from opensn.model.instance import Instance
from opensn.model.link import LinkBase
from opensn.operator.emulator_operator import EmulatorOperator

BASE_DIR = Path(__file__).resolve().parent
STANDARD_DIR = BASE_DIR.parent / "Standard"
if STANDARD_DIR.exists():
    sys.path.append(str(STANDARD_DIR))

from instance_types import TYPE_GROUND_STATION  # noqa: E402
from config import ADDR, PORT  # noqa: E402
from demand_profile import DemandProfile, try_load_profile  # noqa: E402

STEP_SECONDS = 5
K_PATHS = 3
GROUND_STATION_BASE_BPS = 50_000_000
DEFAULT_LINK_CAPACITY = 1_000_000
MIN_ALLOCATION_BPS = 10_000
UTILIZATION_HEADROOM = 0.9
TARGET_KEY = "B4_TARGET_BPS"
UTIL_KEY = "B4_UTIL_PCT"
PROFILE_PATH = os.getenv("B4_DEMAND_PROFILE")


def _require_env() -> Tuple[str, str]:
    if not ADDR or not PORT:
        raise RuntimeError("ADDR and PORT environment variables must be set before running the configurator")
    return ADDR, PORT


@dataclass
class Demand:
    demand_id: str
    src: str
    dst: str
    rate_bps: int
    priority: float = 1.0


@dataclass
class PathCandidate:
    nodes: List[str]
    links: List[str]
    min_capacity: int
    cost: float


def collect_cluster_state(cli: EmulatorOperator) -> Tuple[Dict[str, Instance], Dict[int, Dict[str, LinkBase]], Dict[str, LinkBase]]:
    node_map = cli.get_node_map()
    all_instance_map = {}
    node_link_map = {}
    unique_links = {}
    for node_index in node_map.keys():
        instance_map = cli.get_instance_map(node_index)
        for instance_id, instance in instance_map.items():
            all_instance_map[instance_id] = instance
        link_map = cli.get_link_map(node_index)
        node_link_map[node_index] = link_map
        for link_id, link in link_map.items():
            # 忽略空ID或端点不完整的链接，避免健康检查和TE使用脏数据
            if not link_id or not getattr(link, "end_infos", None) or len(link.end_infos) < 2:
                continue
            if any(not getattr(end_info, "instance_id", "") for end_info in link.end_infos):
                continue
            if link_id not in unique_links:
                unique_links[link_id] = link
    return all_instance_map, node_link_map, unique_links


def build_ground_station_demands(instance_map: Dict[str, Instance], profile: DemandProfile | None) -> List[Demand]:
    grounds = [inst for inst in instance_map.values() if inst.type == TYPE_GROUND_STATION and inst.start]
    grounds.sort(key=lambda inst: inst.instance_id)
    index_map: Dict[int, Instance] = {}
    for inst in grounds:
        try:
            idx = int(inst.extra.get("GroundStationIndex"))  # type: ignore[arg-type]
            index_map[idx] = inst
        except (TypeError, ValueError):
            continue

    demands: List[Demand] = []
    if profile and profile.has_overrides:
        for override in profile.pair_overrides:
            src_inst = index_map.get(override.src_index)
            dst_inst = index_map.get(override.dst_index)
            if not src_inst or not dst_inst:
                logger.warning(
                    "Demand override (%s->%s) skipped because ground station is offline",
                    override.src_index,
                    override.dst_index,
                )
                continue
            demand_id = f"{src_inst.instance_id}__{dst_inst.instance_id}"
            demands.append(Demand(demand_id, src_inst.instance_id, dst_inst.instance_id, override.rate_bps, override.priority))
            if override.bidirectional:
                reverse_id = f"{dst_inst.instance_id}__{src_inst.instance_id}"
                demands.append(Demand(reverse_id, dst_inst.instance_id, src_inst.instance_id, override.rate_bps, override.priority))
        return demands

    default_rate = profile.default_rate_bps if profile else GROUND_STATION_BASE_BPS
    default_priority = profile.default_priority if profile else 1.0
    for idx, left in enumerate(grounds):
        for right in grounds[idx + 1 :]:
            demand_id_fw = f"{left.instance_id}__{right.instance_id}"
            demand_id_bw = f"{right.instance_id}__{left.instance_id}"
            demands.append(Demand(demand_id_fw, left.instance_id, right.instance_id, default_rate, default_priority))
            demands.append(Demand(demand_id_bw, right.instance_id, left.instance_id, default_rate, default_priority))
    return demands


def build_topology_graph(instance_map: Dict[str, Instance], unique_links: Dict[str, LinkBase]) -> Tuple[nx.Graph, Dict[str, int]]:
    graph = nx.Graph()
    active_nodes = {instance_id for instance_id, inst in instance_map.items() if inst.start}
    for instance_id in active_nodes:
        graph.add_node(instance_id)

    for link_id, link in unique_links.items():
        if not link.enable or len(link.end_infos) < 2:
            continue
        src = link.end_infos[0].instance_id
        dst = link.end_infos[1].instance_id
        if src not in active_nodes or dst not in active_nodes:
            continue
        parameter = link.parameter or {}
        capacity = int(parameter.get(PARAMETER_KEY_BANDWIDTH, DEFAULT_LINK_CAPACITY))
        delay = float(parameter.get(PARAMETER_KEY_DELAY, 1))
        graph.add_edge(
            src,
            dst,
            link_id=link_id,
            capacity=max(capacity, MIN_ALLOCATION_BPS),
            delay=delay if delay > 0 else 1.0,
        )
    link_caps = {data["link_id"]: int(data.get("capacity", DEFAULT_LINK_CAPACITY)) for _, _, data in graph.edges(data=True)}
    return graph, link_caps


def enumerate_candidate_paths(graph: nx.Graph, demands: Iterable[Demand]) -> Dict[str, List[PathCandidate]]:
    path_lookup: Dict[str, List[PathCandidate]] = {}
    for demand in demands:
        if demand.src not in graph or demand.dst not in graph:
            continue
        try:
            generator = nx.shortest_simple_paths(graph, demand.src, demand.dst, weight="delay")
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            continue
        candidates: List[PathCandidate] = []
        for nodes_path in itertools.islice(generator, K_PATHS):
            link_ids: List[str] = []
            min_capacity = float("inf")
            total_delay = 0.0
            for left, right in zip(nodes_path, nodes_path[1:]):
                edge_data = graph.edges[left, right]
                link_ids.append(edge_data["link_id"])
                min_capacity = min(min_capacity, float(edge_data.get("capacity", DEFAULT_LINK_CAPACITY)))
                total_delay += float(edge_data.get("delay", 1.0))
            candidates.append(PathCandidate(nodes=list(nodes_path), links=link_ids, min_capacity=int(min_capacity), cost=total_delay))
        if candidates:
            path_lookup[demand.demand_id] = candidates
    return path_lookup


def solve_traffic_engineering(demands: List[Demand], candidate_paths: Dict[str, List[PathCandidate]], link_caps: Dict[str, int]) -> Dict[Tuple[str, int], float]:
    active_demands = [d for d in demands if d.demand_id in candidate_paths]
    if not active_demands:
        return {}
    prob = LpProblem("b4_te", LpMaximize)
    var_map: Dict[Tuple[str, int], LpVariable] = {}

    for demand in active_demands:
        for idx, path in enumerate(candidate_paths[demand.demand_id]):
            upper_bound = min(demand.rate_bps, path.min_capacity)
            var = LpVariable(f"x_{demand.demand_id}_{idx}", lowBound=0, upBound=max(upper_bound, MIN_ALLOCATION_BPS))
            var_map[(demand.demand_id, idx)] = var
        prob += lpSum(var_map[(demand.demand_id, idx)] for idx in range(len(candidate_paths[demand.demand_id]))) <= demand.rate_bps

    for link_id, capacity in link_caps.items():
        prob += lpSum(
            var
            for (demand_id, idx), var in var_map.items()
            if link_id in candidate_paths[demand_id][idx].links
        ) <= capacity * UTILIZATION_HEADROOM

    prob += lpSum(
        demand.priority * var_map[(demand.demand_id, idx)]
        for demand in active_demands
        for idx in range(len(candidate_paths[demand.demand_id]))
    )

    prob.solve(PULP_CBC_CMD(msg=False))
    if prob.status != LpStatusOptimal:
        logger.warning("B4 solver did not converge: status=%s", prob.status)
        return {}

    allocations: Dict[Tuple[str, int], float] = {}
    for key, var in var_map.items():
        value = var.value()
        if value is None or value < MIN_ALLOCATION_BPS:
            continue
        allocations[key] = value
    return allocations


def accumulate_link_usage(allocations: Dict[Tuple[str, int], float], candidate_paths: Dict[str, List[PathCandidate]]) -> Dict[str, float]:
    usage: Dict[str, float] = defaultdict(float)
    for (demand_id, idx), value in allocations.items():
        for link_id in candidate_paths[demand_id][idx].links:
            usage[link_id] += value
    return usage


def update_link_parameters(cli: EmulatorOperator, node_link_map: Dict[int, Dict[str, object]], usage_map: Dict[str, float], link_caps: Dict[str, int]) -> None:
    for node_index, link_map in node_link_map.items():
        for link_id, link in link_map.items():
            # Skip links that are not enabled or have missing endpoints to avoid daemon errors
            if not getattr(link, "enable", False):
                continue
            if not getattr(link, "end_infos", None) or len(link.end_infos) < 2:
                continue
            # Daemon对vlink不支持B4_*参数，直接跳过，避免WARN噪声
            if getattr(link, "type", "") == "vlink":
                continue
            parameter = dict(link.parameter or {})
            capacity = int(parameter.get(PARAMETER_KEY_BANDWIDTH, link_caps.get(link_id, DEFAULT_LINK_CAPACITY)))
            target = int(usage_map.get(link_id, 0.0))

            # Push the planned bandwidth to the live parameter so data plane follows the TE decision.
            if target > 0:
                parameter[PARAMETER_KEY_BANDWIDTH] = int(max(MIN_ALLOCATION_BPS, min(capacity, target)))
            else:
                parameter.setdefault(PARAMETER_KEY_BANDWIDTH, capacity)

            parameter[TARGET_KEY] = target
            parameter[UTIL_KEY] = int(min(100, (target / capacity) * 100)) if capacity else 0
            cli.put_link_parameter(node_index, link_id, parameter)


def log_round_summary(demands: List[Demand], allocations: Dict[Tuple[str, int], float]) -> None:
    delivered: Dict[str, float] = defaultdict(float)
    for (demand_id, _), value in allocations.items():
        delivered[demand_id] += value
    total_throughput = sum(delivered.values())
    unsatisfied = sum(max(0.0, demand.rate_bps - delivered.get(demand.demand_id, 0.0)) for demand in demands)
    logger.info(
        "B4 round completed: satisfied {:.3f} Gbps, unmet {:.3f} Gbps, active flows {}",
        total_throughput / 1e9,
        unsatisfied / 1e9,
        len(delivered),
    )


def main() -> None:
    addr, port = _require_env()
    cli = EmulatorOperator(addr, port)
    logger.info("Connected to OpenSN master %s:%s for B4 control", addr, port)
    profile: DemandProfile | None = None
    if PROFILE_PATH:
        profile = try_load_profile(PROFILE_PATH)
        if profile:
            logger.info(
                "Loaded demand profile %s (overrides=%d)",
                PROFILE_PATH,
                len(profile.pair_overrides),
            )

    while True:
        start_ts = time.time()
        try:
            instance_map, node_link_map, unique_links = collect_cluster_state(cli)
            demands = build_ground_station_demands(instance_map, profile)
            if not demands:
                logger.debug("No running ground stations detected; skipping round")
                time.sleep(STEP_SECONDS)
                continue
            # Wait until链接都处于启用且端点完整，避免 daemon 报 not enabled
            unhealthy_links = [lid for lid, lk in unique_links.items() if (not getattr(lk, "end_infos", None)) or len(lk.end_infos) < 2 or any(not getattr(e, "instance_id", "") for e in lk.end_infos)]
            if unhealthy_links:
                logger.debug("Links not ready, skip round: %d unhealthy", len(unhealthy_links))
                time.sleep(STEP_SECONDS)
                continue
            graph, link_caps = build_topology_graph(instance_map, unique_links)
            if graph.number_of_edges() == 0:
                logger.warning("Topology graph is empty, waiting for links to register")
                time.sleep(STEP_SECONDS)
                continue
            candidate_paths = enumerate_candidate_paths(graph, demands)
            if not candidate_paths:
                logger.warning("No candidate paths found for current demands")
                time.sleep(STEP_SECONDS)
                continue
            allocations = solve_traffic_engineering(demands, candidate_paths, link_caps)
            if not allocations:
                logger.warning("Solver produced no allocations; retaining previous parameters")
            else:
                usage_map = accumulate_link_usage(allocations, candidate_paths)
                update_link_parameters(cli, node_link_map, usage_map, link_caps)
                log_round_summary(demands, allocations)
        except Exception as exc:  # pragma: no cover - defensive loop guard
            logger.exception("B4 control loop error: %s", exc)
        elapsed = time.time() - start_ts
        sleep_duration = max(1.0, STEP_SECONDS - elapsed)
        time.sleep(sleep_duration)


if __name__ == "__main__":
    main()
