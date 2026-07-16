import time
import json
import redis
import subprocess
from loguru import logger

from opensn.operator.emulator_operator import EmulatorOperator
from opensn.model.instance import Instance
from address_type import LINK_V4_ADDR_KEY
from traffic_config import TrafficConfig, TrafficFlow
from instance_types import EX_ORBIT_INDEX, EX_SATELLITE_INDEX, EX_TLE0_KEY, TYPE_SATELLITE

# Redis te:demands key
_TE_DEMANDS_KEY = "te:demands"
_POLICY_APPLIED_KEY = "te:policy:applied_signature"
# 流量类别：根据带宽决定，>=500K 为背景流，<500K 为控制流
_BW_THRESHOLD_K = 500

# 每隔多少个拓扑循环 tick 做一次存活检查
_LIVENESS_CHECK_INTERVAL = 12


class TrafficManager:
    """
    管理卫星容器内 iperf3 的服务端/客户端进程。
    """

    def __init__(self, cli: EmulatorOperator, config: TrafficConfig) -> None:
        self.cli = cli
        self.config = config
        self._server_started: set[str] = set()
        self._last_dest_ip: dict[str, str] = {}
        self._tick: int = 0
        self._start_time: float = time.time()
        self._log_dir_created: set[str] = set()
        self._log_truncated: set[tuple[str, str]] = set()
        self._auto_flows_resolved: bool = False
        self._client_started_once: set[str] = set()
        self._last_applied_policy: dict[str, str] = {}
        # Redis 客户端，用于写入 te:demands 让 Lyapunov 引擎感知流量需求
        try:
            self._redis = redis.Redis(host='localhost', port=6379, decode_responses=True)
        except Exception as e:
            logger.warning("无法连接 Redis，Lyapunov 引擎将无法感知流量需求: {}", e)
            self._redis = None

    # ------------------------------------------------------------------
    # Helper to execute commands in containers via docker exec
    # ------------------------------------------------------------------
    def _exec_instance(self, instance: Instance, cmd: str, args: list = None, detach: bool = False, timeout: int = 15) -> dict:
        if args is None: args = []
        container_name = f"{instance.type}_{instance.instance_id}"
        full_cmd = ["docker", "exec"]
        if detach: full_cmd.append("-d")
        full_cmd.extend([container_name, cmd] + args)
        try:
            res = subprocess.run(full_cmd, capture_output=not detach, text=True, timeout=timeout)
            if detach: return {"exit_code": 0, "stdout": "", "stderr": ""}
            return {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "timeout"}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _build_topology_links(self) -> dict[str, set]:
        """从 Redis 构建拓扑邻接表，用于验证节点间是否有直接链路"""
        if not self._redis:
            logger.warning("Redis 未连接，跳过拓扑加载")
            return {}
        links = {}  # src -> set of dst
        try:
            keys = self._redis.keys("topo:link:Satellite_*")
            logger.debug("从 Redis 加载到 {} 个 topo:link 键", len(keys))
            for key in keys:
                key_str = str(key)
                # key 格式: topo:link:Satellite_xxx_Satellite_yyy
                if "_Satellite_" in key_str:
                    parts = key_str.split("_Satellite_")
                    if len(parts) >= 2:
                        # src = "topo:link:Satellite_xxx" 或直接是 "xxx"
                        src = parts[0].replace("topo:link:Satellite_", "")
                        dst = parts[1]
                        if src and dst:
                            if src not in links:
                                links[src] = set()
                            links[src].add(dst)
            logger.debug("解析出 {} 个源节点", len(links))
        except Exception as e:
            logger.warning("构建拓扑邻接表失败: {}", e)
        return links

    def _resolve_auto_flows(self, all_instance_map: dict[str, Instance]) -> None:
        """按 auto_flows.pairs 中的序号自动生成流

        注意：不验证拓扑连通性，Lyapunov 会自动跳过找不到路径的流。
        """
        af = self.config.auto_flows
        if not af.pairs:
            return

        satellites = sorted(
            [inst for inst in all_instance_map.values() if inst.type == TYPE_SATELLITE],
            key=self._satellite_sort_key,
        )

        if not satellites:
            return

        logger.info("自动发现 {} 颗卫星，按序号生成流：", len(satellites))
        for idx, sat in enumerate(satellites):
            logger.info("   [{}] {}", idx, sat.instance_id)

        # 收集 Lyapunov 需求的流量列表
        lyapunov_flows = []

        for pair_idx, pair in enumerate(af.pairs):
            if isinstance(pair, (list, tuple)):
                s_idx, r_idx = pair[0], pair[1]
                overrides = {}
            else:
                s_idx = pair["sender"]
                r_idx = pair["receiver"]
                overrides = {k: v for k, v in pair.items() if k not in ("sender", "receiver")}

            if s_idx >= len(satellites) or r_idx >= len(satellites):
                logger.warning("auto_flows pairs[{}] 序号超限", pair_idx)
                continue

            sender_id = satellites[s_idx].instance_id
            receiver_id = satellites[r_idx].instance_id

            flow = TrafficFlow(
                flow_id=f"auto_flow_{pair_idx}",
                sender_instance_id=sender_id,
                receiver_instance_id=receiver_id,
                protocol=overrides.get("protocol", af.protocol),
                bandwidth=overrides.get("bandwidth", af.bandwidth),
                duration=overrides.get("duration", af.duration),
                parallel=overrides.get("parallel", af.parallel),
                port=overrides.get("port", af.port_start + pair_idx),
                interval=overrides.get("interval", af.interval),
                omit=overrides.get("omit", af.omit),
            )
            self.config.flows.append(flow)

            # 准备写入 Redis te:demands 的流量需求
            bw_str = overrides.get("bandwidth", af.bandwidth)
            bw_k = self._parse_bandwidth_kbps(bw_str)
            traffic_class = "class_3_background" if bw_k >= _BW_THRESHOLD_K else "class_1_urllc"
            lyapunov_flows.append({
                "id": f"iperf_{flow.flow_id}",
                "src": f"Satellite_{sender_id}",
                "dst": f"Satellite_{receiver_id}",
                "class": traffic_class,
                "demand": bw_k
            })

        logger.info("[TrafficManager] 生成 {} 条流，等待 Lyapunov 引擎计算路径", len(lyapunov_flows))

        # 写入 Redis te:demands
        self._write_demands_to_redis(lyapunov_flows)

        self._auto_flows_resolved = True

    @staticmethod
    def _satellite_sort_key(instance: Instance) -> tuple[int, int, str]:
        extra = getattr(instance, "extra", {}) or {}
        tle0 = str(extra.get(EX_TLE0_KEY, ""))
        parts = tle0.split("_")
        if len(parts) == 3 and parts[0] == "NODE":
            try:
                return (int(parts[1]), int(parts[2]), instance.instance_id)
            except ValueError:
                pass
        try:
            return (
                int(extra.get(EX_ORBIT_INDEX, 0)),
                int(extra.get(EX_SATELLITE_INDEX, 0)),
                instance.instance_id,
            )
        except (TypeError, ValueError):
            return (getattr(instance, "node_index", 0), 0, instance.instance_id)

    def _parse_bandwidth_kbps(self, bw_str: str) -> float:
        """将带宽字符串（如 "1500K", "10M"）转换为 Kbps 数值"""
        if not bw_str or bw_str == "0":
            return 0.0
        bw_str = bw_str.strip().upper()
        try:
            if bw_str.endswith("K"):
                return float(bw_str[:-1])
            elif bw_str.endswith("M"):
                return float(bw_str[:-1]) * 1000
            elif bw_str.endswith("G"):
                return float(bw_str[:-1]) * 1000000
            else:
                return float(bw_str)
        except (ValueError, IndexError):
            return 0.0

    def _write_demands_to_redis(self, flows: list) -> None:
        """将流量需求写入 Redis te:demands，让 Lyapunov 引擎感知"""
        if not self._redis:
            logger.warning("Redis 未连接，跳过写入 te:demands")
            return
        try:
            demands_json = json.dumps(flows)
            self._redis.set(_TE_DEMANDS_KEY, demands_json)
            logger.debug("[TrafficManager] 写入 {} 条流量需求到 Redis te:demands", len(flows))
        except Exception as e:
            logger.error("写入 te:demands 失败: {}", e)

    def _write_current_flows_to_redis(self) -> None:
        """从当前已解析的 flows 中提取流量需求并写入 Redis te:demands

        关键：此方法在每次 update 时调用，确保 te:demands 始终有数据，
        让 Lyapunov 引擎能够持续感知流量需求并计算路由。
        """
        if not self.config.flows:
            return
        lyapunov_flows = []
        for flow in self.config.flows:
            bw_k = self._parse_bandwidth_kbps(flow.bandwidth)
            traffic_class = "class_3_background" if bw_k >= _BW_THRESHOLD_K else "class_1_urllc"
            lyapunov_flows.append({
                "id": f"iperf_{flow.flow_id}",
                "src": f"Satellite_{flow.sender_instance_id}",
                "dst": f"Satellite_{flow.receiver_instance_id}",
                "class": traffic_class,
                "demand": bw_k
            })
        self._write_demands_to_redis(lyapunov_flows)

    def update(self, all_instance_map: dict[str, Instance], node_link_map: dict[int, dict]) -> None:
        if not self.config.enabled: return
        if not self._auto_flows_resolved: self._resolve_auto_flows(all_instance_map)

        elapsed = time.time() - self._start_time
        if elapsed < self.config.startup_delay_seconds:
            self._tick += 1
            # 即使在 startup_delay 期间，也要持续写入 te:demands
            # 确保 Lyapunov 引擎能够感知到流量需求
            self._write_current_flows_to_redis()
            return

        self._tick += 1
        # 持续写入 te:demands，让 Lyapunov 持续感知流量需求
        self._write_current_flows_to_redis()

        do_liveness = (self._tick % _LIVENESS_CHECK_INTERVAL == 0)
        for flow in self.config.flows:
            self._process_flow(flow, all_instance_map, node_link_map, do_liveness)

    def stop_all(self, all_instance_map: dict[str, Instance]) -> None:
        if not self.config.enabled: return
        for flow in self.config.flows:
            receiver = all_instance_map.get(flow.receiver_instance_id)
            sender = all_instance_map.get(flow.sender_instance_id)
            if receiver and receiver.start: self._kill_server(flow, receiver)
            if sender and sender.start: self._kill_client(flow, sender)
        self._server_started.clear()
        self._last_dest_ip.clear()
        self._client_started_once.clear()
        self._last_applied_policy.clear()

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    def _process_flow(self, flow: TrafficFlow, all_instance_map: dict[str, Instance], 
                      node_link_map: dict[int, dict], do_liveness: bool) -> None:
        sender = all_instance_map.get(flow.sender_instance_id)
        receiver = all_instance_map.get(flow.receiver_instance_id)
        if not (sender and receiver and sender.start and receiver.start): return

        self._ensure_log_dir(receiver)
        self._ensure_log_dir(sender)

        # 检查服务端存活
        if flow.flow_id not in self._server_started or (do_liveness and not self._is_process_alive(receiver, f"[i]perf3 -s -p {flow.port}")):
            if not self._start_server(flow, receiver): return

        policy_signature = self._read_policy_signature(flow)
        old_signature = self._last_applied_policy.get(flow.flow_id)
        policy_changed = bool(policy_signature and policy_signature != old_signature)

        # 调试阶段：每条 flow 只启动一次
        # 避免 iperf 正常结束后被 TrafficManager 反复重启，导致日志和统计混乱
        if flow.flow_id in self._client_started_once:
            if not policy_changed:
                return

            dest_ip = self._resolve_dest_ip(flow, sender, receiver, node_link_map)
            if not dest_ip:
                return

            dest_changed = self._last_dest_ip.get(flow.flow_id) != dest_ip
            if policy_changed:
                logger.info(
                    "[TrafficManager] 检测到 flow {} 的 SRv6 策略已生效，重启 client 以验证控制面路径",
                    flow.flow_id,
                )
                self._start_client(flow, sender, dest_ip)
                self._last_dest_ip[flow.flow_id] = dest_ip
                self._last_applied_policy[flow.flow_id] = policy_signature
            if dest_changed:
                logger.debug(
                    "[TrafficManager] flow {} 目的地址随新策略解析为 {}",
                    flow.flow_id,
                    dest_ip,
                )
            return

        dest_ip = self._resolve_dest_ip(flow, sender, receiver, node_link_map)
        if not dest_ip: return

        logger.info(
            "[TrafficManager] 首次启动 flow {}: {} -> {}:{}",
            flow.flow_id,
            sender.instance_id,
            dest_ip,
            flow.port,
        )

        self._start_client(flow, sender, dest_ip)
        self._last_dest_ip[flow.flow_id] = dest_ip
        self._client_started_once.add(flow.flow_id)

    def _read_policy_signature(self, flow: TrafficFlow) -> str:
        """读取控制面成功下发的 SRv6 策略签名。"""
        if not self._redis:
            return ""
        policy_flow_id = f"iperf_{flow.flow_id}"
        try:
            signature = self._redis.hget(_POLICY_APPLIED_KEY, policy_flow_id)
        except Exception as e:
            logger.debug("读取 SRv6 策略生效标记失败: {}", e)
            return ""
        return signature or ""

    def _ensure_log_dir(self, instance: Instance) -> None:
        if instance.instance_id in self._log_dir_created: return
        try:
            # 创建目录并赋予权限，确保宿主机脚本可以读取日志
            self._exec_instance(instance, "sh", ["-c", f"mkdir -p {self.config.log_dir} && chmod -R 777 {self.config.log_dir}"])
            self._log_dir_created.add(instance.instance_id)
        except Exception: pass

    def _server_log_path(self, flow: TrafficFlow) -> str:
        return f"{self.config.log_dir}/{flow.flow_id}_server.log"

    def _client_log_path(self, flow: TrafficFlow) -> str:
        return f"{self.config.log_dir}/{flow.flow_id}_client.log"

    def _truncate_log_once(self, instance: Instance, log_path: str) -> None:
        key = (instance.instance_id, log_path)
        if key in self._log_truncated: return
        self._log_truncated.add(key)
        try:
            self._exec_instance(instance, "sh", ["-c", f": > {log_path}"])
        except Exception: pass

    def _verify_reachable(self, sender: Instance, dest_ip: str, port: int) -> bool:
        cmd = f"nc -z -w 1 {dest_ip} {port} 2>/dev/null"
        try:
            result = self._exec_instance(sender, "sh", ["-c", cmd], detach=False, timeout=5)
            return result.get("exit_code", 1) == 0
        except Exception: return False

    def _start_server(self, flow: TrafficFlow, receiver: Instance) -> bool:
        log_path = self._server_log_path(flow)
        self._truncate_log_once(receiver, log_path)
        self._kill_server(flow, receiver)
        start_cmd = (f"printf '\\n--- [server restart %s] ---\\n' \"$(date +%H:%M:%S)\" >> {log_path}; "
                     f"iperf3 -s -p {flow.port} -i {flow.interval} 2>&1 | awk '{{print strftime(\"[%Y-%m-%d %H:%M:%S]\"), $0; fflush()}}' >> {log_path}")
        try:
            self._exec_instance(receiver, "sh", ["-c", start_cmd], detach=True)
            verify_cmd = f"for i in $(seq 1 20); do ss -ltn 'sport = :{flow.port}' 2>/dev/null | grep -q ':{flow.port}' && exit 0; sleep 0.2; done; exit 1"
            result = self._exec_instance(receiver, "sh", ["-c", verify_cmd], detach=False, timeout=10)
            if result.get("exit_code", 1) == 0:
                self._server_started.add(flow.flow_id)
                return True
        except Exception: pass
        return False

    def _kill_server(self, flow: TrafficFlow, receiver: Instance) -> None:
        pattern = f"[i]perf3 -s -p {flow.port}"
        cmd = f"pkill -TERM -f '{pattern}' 2>/dev/null; sleep 0.3; pkill -KILL -f '{pattern}' 2>/dev/null; true"
        try: self._exec_instance(receiver, "sh", ["-c", cmd])
        except Exception: pass

    def _start_client(self, flow: TrafficFlow, sender: Instance, dest_ip: str) -> None:
        log_path = self._client_log_path(flow)
        self._truncate_log_once(sender, log_path)
        args_str = self._build_client_args_str(flow, dest_ip)
        self._kill_client(flow, sender)
        cmd = (f"printf '\\n--- [client restart %s -> {dest_ip}] ---\\n' \"$(date +%H:%M:%S)\" >> {log_path}; "
               f"iperf3 {args_str} 2>&1 | awk '{{print strftime(\"[%Y-%m-%d %H:%M:%S]\"), $0; fflush()}}' >> {log_path}")
        try: self._exec_instance(sender, "sh", ["-c", cmd], detach=True)
        except Exception: pass

    def _kill_client(self, flow: TrafficFlow, sender: Instance) -> None:
        pattern = f"[i]perf3 -c .*-p {flow.port}"
        cmd = f"pkill -TERM -f '{pattern}' 2>/dev/null; sleep 0.3; pkill -KILL -f '{pattern}' 2>/dev/null; true"
        try: self._exec_instance(sender, "sh", ["-c", cmd])
        except Exception: pass

    @staticmethod
    def _build_client_args_str(flow: TrafficFlow, dest_ip: str) -> str:
        # 强制增加 -M 1200 确保控制信道 TCP 握手成功（应对 SRv6 头部开销）
        # 增加 -l 1000 减小 UDP 报文长度，防止数据面分片压力
        parts = [
            "-c", dest_ip, 
            "-p", str(flow.port), 
            "-t", str(flow.duration), 
            "-P", str(flow.parallel), 
            "-i", str(flow.interval),
            "-M", "1200"
        ]
        if flow.bandwidth and flow.bandwidth != "0": 
            parts += ["-b", flow.bandwidth]
        if flow.protocol.lower() == "udp": 
            parts += ["-u", "-l", "1000"]
        if flow.omit > 0: 
            parts += ["-O", str(flow.omit)]
        return " ".join(parts)

    def _resolve_dest_ip(self, flow: TrafficFlow, sender: Instance, receiver: Instance, node_link_map: dict[int, dict]) -> str:
        """解析 receiver 的 OpenSN 数据面 IPv4 地址。"""
        if flow.destination_ip:
            return flow.destination_ip

        receiver_ips = self._get_instance_10_ips(receiver)
        if not receiver_ips:
            logger.warning(
                "[TrafficManager] 无法为 receiver {} 找到 10.x 数据面地址，跳过该流",
                receiver.instance_id,
            )
            return ""

        for candidate_ip in receiver_ips:
            sender_src_ip = self._get_route_src_ip(sender, candidate_ip)
            if not sender_src_ip or not sender_src_ip.startswith("10."):
                continue

            receiver_reply_src_ip = self._get_route_src_ip(receiver, sender_src_ip)
            if receiver_reply_src_ip == candidate_ip:
                if candidate_ip != receiver_ips[0]:
                    logger.info(
                        "[TrafficManager] flow {} 选择 receiver 地址 {}，替代默认首地址 {}",
                        flow.flow_id,
                        candidate_ip,
                        receiver_ips[0],
                    )
                return candidate_ip

        logger.warning(
            "[TrafficManager] flow {} 未找到回程对称的 receiver 地址，回退到 {}",
            flow.flow_id,
            receiver_ips[0],
        )
        return receiver_ips[0]

    def _get_instance_10_ips(self, instance: Instance) -> list[str]:
        try:
            result = self._exec_instance(
                instance,
                "sh",
                [
                    "-c",
                    "ip -4 -o addr show | awk '{print $4}' | grep '^10\.' | cut -d'/' -f1",
                ],
                timeout=5,
            )
            if result.get("exit_code") == 0:
                return [line.strip() for line in result.get("stdout", "").splitlines() if line.strip()]
        except Exception:
            pass
        return []

    def _get_route_src_ip(self, instance: Instance, dest_ip: str) -> str:
        try:
            result = self._exec_instance(
                instance,
                "sh",
                [
                    "-c",
                    f"ip route get {dest_ip} 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1",
                ],
                timeout=5,
            )
            if result.get("exit_code") == 0:
                return result.get("stdout", "").strip()
        except Exception:
            pass
        return ""

    def _is_process_alive(self, instance: Instance, pattern: str) -> bool:
        try:
            result = self._exec_instance(instance, "pgrep", ["-f", pattern])
            return result.get("exit_code", 1) == 0
        except Exception:
            return False
