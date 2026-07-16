import json
from dataclasses import dataclass, field


@dataclass
class TrafficFlow:
    flow_id: str
    sender_instance_id: str        # 发送方卫星实例 ID（运行时填入）
    receiver_instance_id: str      # 接收方卫星实例 ID（运行时填入）
    protocol: str = "tcp"          # "tcp" 或 "udp"
    bandwidth: str = "0"           # "0" 不限速；或 "500K"、"10M"、"1G"
    duration: int = 86400          # 持续时间（秒）
    parallel: int = 1              # iperf3 并发流数
    port: int = 5201               # iperf3 监听端口
    interval: float = 1.0          # 统计输出间隔（秒）
    omit: int = 0                  # 预热忽略秒数（TCP 慢启动）
    destination_ip: str = ""       # 手动指定目标 IP，留空自动解析


@dataclass
class AutoFlowConfig:
    """
    自动按卫星序号建流，无需填写实例 ID。
    程序启动时自动发现所有卫星，优先按 node_index 排列，
    pairs 中的数字代表 topology_config 中的卫星序号（从 0 开始）。
    """
    pairs: list = field(default_factory=list)  # [[发送方序号, 接收方序号], ...]
    protocol: str = "udp"
    bandwidth: str = "0"
    duration: int = 86400
    parallel: int = 1
    port_start: int = 5201         # 第一对流用此端口，后续每对 +1
    interval: float = 1.0
    omit: int = 0


@dataclass
class TrafficConfig:
    enabled: bool = False
    startup_delay_seconds: int = 60
    log_dir: str = "/share/user/iperf_logs"
    auto_flows: AutoFlowConfig = field(default_factory=AutoFlowConfig)
    flows: list = field(default_factory=list)   # 手动指定的流（兼容旧格式）


def load_traffic_config(path: str) -> TrafficConfig:
    config = TrafficConfig()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return config
    except Exception as e:
        from loguru import logger
        logger.error("Failed to load traffic config from {}: {}", path, e)
        return config

    config.enabled = data.get("enabled", False)
    config.startup_delay_seconds = data.get("startup_delay_seconds", 60)
    config.log_dir = data.get("log_dir", "/share/user/iperf_logs")

    # 自动流配置
    af = data.get("auto_flows", {})
    if af:
        config.auto_flows.pairs = af.get("pairs", [])
        for key in ("protocol", "bandwidth", "duration", "parallel",
                    "port_start", "interval", "omit"):
            if key in af:
                setattr(config.auto_flows, key, af[key])

    # 手动流配置（兼容旧格式）
    for fd in data.get("flows", []):
        flow = TrafficFlow(
            flow_id=fd["flow_id"],
            sender_instance_id=fd["sender_instance_id"],
            receiver_instance_id=fd["receiver_instance_id"],
        )
        for key in ("protocol", "bandwidth", "duration", "parallel",
                    "port", "interval", "omit", "destination_ip"):
            if key in fd:
                setattr(flow, key, fd[key])
        config.flows.append(flow)
    return config
