# OpenSN Deployment, Build, and Run Guide

> This document captures the full workflow we validated on Jan 18, 2026, including every command we executed and the configuration edits made specifically for this environment. Use it as an end-to-end checklist when bringing up OpenSN on a fresh host.

## 1. Repository Layout (abridged)

```
OpenSN-Library/
├── config/                    # Runtime config synced from daemon/config/
├── daemon/                    # NodeDaemon sources, scripts, BPF code
├── dependencies/              # Docker build contexts for etcd/influxdb/codeserver
├── container-base/            # Base images for satellite & ground-station nodes
├── TopoConfigurators/         # Python SDK + sample topology controllers
├── tools/                     # Helpers (namespace generator, packet capture, etc.)
├── example/test_topologies/   # Reference emulation configs and topologies
└── ui/                        # React web console
```

## 2. Host Requirements

1. **OS**: Ubuntu (tested on 22.04, kernel tuning required after every reboot).
2. **Docker Engine**: `24.0.5` (`sudo apt install docker.io` or follow Docker docs).
3. **Go toolchain**: ≥ 1.20 (required for `go -C` used in Make targets).
4. **Python**: System Python 3.x (TopoConfigurator SDK, CodeServer image build).
5. **Privileges**: You need sudo access for Docker socket and kernel tweaks.

## 3. Kernel Preparation (Section 4.1 from readme_zh.md)

Run once per boot to guarantee enough inotify nodes and ARP table capacity:

```bash
sudo sh -c 'echo 4096 > /proc/sys/fs/inotify/max_user_instances'
sudo sh -c 'echo 8192 > /proc/sys/net/ipv4/neigh/default/gc_thresh1'
sudo sh -c 'echo 16384 > /proc/sys/net/ipv4/neigh/default/gc_thresh2'
sudo sh -c 'echo 32768 > /proc/sys/net/ipv4/neigh/default/gc_thresh3'
```

Persist into `/etc/sysctl.d/*.conf` if desired.

## 4. Dependency Images (Etcd, InfluxDB, CodeServer)

We removed hard-coded secrets from `dependencies/custom-codeserver/Dockerfile` by deleting both `ARG SUDO_PASSWORD` and `ENV SUDO_PASSWORD`. This avoids `SecretsUsedInArgOrEnv` warnings during `docker build`. Provide `SUDO_PASSWORD` through `docker run -e` if needed.

Build and export all dependency images from the repo root:

```bash
cd dependencies
make build          # builds all three images and emits *.tar.gz
cd -
```

Resulting archives:
- `opensn_etcd.tar.gz`
- `opensn_influxdb.tar.gz`
- `opensn_codeserver.tar.gz`

Load them into Docker (if building on a different host):

```bash
docker load -i dependencies/opensn_etcd.tar.gz
docker load -i dependencies/opensn_influxdb.tar.gz
docker load -i dependencies/opensn_codeserver.tar.gz
```

## 5. Launch Dependency Containers

Use the provided script to stop stale instances and run fresh ones with the expected ports (2379/8086/8079) and CodeServer workspace mount:

```bash
bash daemon/scripts/start_depend_service.sh
```

Sample output we observed:

```
opensn_etcd
opensn_influxdb
opensn_codeserver
3dae...  # etcd container ID
9338...  # influxdb container ID
7b90...  # code-server container ID
```

Verify with `docker ps`:

```
CONTAINER ID   IMAGE                       PORTS
7b90...        realssd/opensn_codeserver   0.0.0.0:8079->8443/tcp
9338...        realssd/opensn_influxdb     0.0.0.0:8086->8086/tcp
3dae...        realssd/opensn_etcd         0.0.0.0:2379->2379/tcp
```

## 6. Build NodeDaemon

From the repository root:

```bash
make node-daemon
make sync-config   # copies daemon/config/config.json -> config/config.json
```

This produces `./NodeDaemon` in the repo root and keeps the runtime config in sync.

## 7. Runtime Configuration (`config/config.json`)

We applied the following edits compared to the default template:

```json
{
  "app": {
    "is_servant": false,
    "master_address": "192.168.1.129",
    "listen_port": 8080,
    "enable_monitor": true,
    "enable_code_server": true,
    "interface_name": "ens33",            // must match host NIC name
    "debug": false,
    "instance_capacity": 100,               // capped at 100 satellite nodes
    "monitor_interval": 1,
    "parallel_num": 64
  },
  "dependency": {
    "etcd_addr": "192.168.1.129",
    "etcd_port": 2379,
    "influxdb_addr": "192.168.1.129",
    "influxdb_port": 8086,
    "influxdb_token": "1145141919810",
    "influxdb_org": "satellite_emulator",
    "influxdb_bucket": "monitor",
    "code_server_addr": "192.168.1.129",
    "code_server_port": 8079,
    "docker_host_path": "/var/run/docker.sock"
  },
  "device": {
    "FixPhysicalLink": [],
    "MultiplexPhysicalLink": []
  }
}
```

Adjust `interface_name`, `*_addr`, and capacity numbers to match your network before launching. Servant nodes should set `is_servant: true` and point `master_address` at the primary node.

## 8. Start NodeDaemon

Run as root so it can talk to Docker and manage network namespaces:

```bash
sudo ./NodeDaemon
```

Expected boot log (abridged):

```
[INFO] Init Config Success, Config is {{false 192.168.1.129 ens33 8080 true true false 100 1 64} {...}}
[INFO] Run InstanceManage Module.
[INFO] Run Link Manager Module.
[INFO] Run configWatchModule Module.
[INFO] Run Link Parameter Module Module.
[INFO] Run WebShell Module Module.
[INFO] Run MasterNode Module.
[INFO] Run MonitorModule Module.
[GIN-debug] [WARNING] Running in "debug" mode...
```

To switch Gin into production mode, export `GIN_MODE=release` before launching or call `gin.SetMode(gin.ReleaseMode)` in the code.

## 9. Access the Web Console

Navigate to `http://192.168.1.129:8080` (replace IP/port as configured) to open the UI. From there you can:

1. Upload an emulation configuration and topology JSON (see `example/test_topologies/`).
2. Monitor upload logs until the topology loads.
3. Click **Start** to bring the constellation online.
4. Launch a Topology Configurator either inside CodeServer (`docker exec -it opensn_codeserver bash`) or locally via `TopoConfigurators/opensn`.
5. Use the 3D map, node details, WebShell, and packet capture tools exposed in the UI.

## 10. Optional: Topology Configurator Basics

- Sample controller: `TopoConfigurators/Standard/main.py`
- Python SDK: `TopoConfigurators/opensn/`
- Requirements: `pip install -r TopoConfigurators/opensn/requirements.txt`
- Controller communicates with NodeDaemon through Etcd/InfluxDB to orchestrate node/edge state.

## 11. Maintenance and Troubleshooting

- **Restart dependencies**: rerun `bash daemon/scripts/start_depend_service.sh`.
- **Cleanup**: `bash daemon/scripts/delete_link_prefix.sh` removes leftover links/containers.
- **Config drift**: run `make sync-config` whenever `daemon/config/config.json` changes.
- **Kernel params lost**: reapply Section 3 commands after every reboot.
- **Scaling out**: replicate `NodeDaemon` binary + config on additional hosts, update `interface_name`, set `is_servant=true`, and ensure `master_address` reaches the primary node.

## 12. Command Summary

| Step | Command |
| ---- | ------- |
| Kernel prep | `sudo sh -c 'echo ...'` (four commands) |
| Build dependencies | `cd dependencies && make build` |
| Load images (optional) | `docker load -i dependencies/opensn_*.tar.gz` |
| Start dependencies | `bash daemon/scripts/start_depend_service.sh` |
| Build daemon | `make node-daemon` |
| Sync config | `make sync-config` |
| Launch daemon | `sudo ./NodeDaemon` |
| Access UI | `http://<master_addr>:<listen_port>` |

With these steps the full OpenSN stack—dependencies, daemon, and UI—runs end to end on a single machine, matching the configuration and changes validated in this session.
