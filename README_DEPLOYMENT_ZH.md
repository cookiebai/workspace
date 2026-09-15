# OpenSN 部署、编译与运行指南

> 本指南记录我们在 2026 年 1 月 18 日完成的完整流程，涵盖所有执行过的命令与针对当前环境做过的配置修改。可作为在新主机上部署 OpenSN 的端到端检查清单。

## 1. 仓库结构概览

```
OpenSN-Library/
├── config/                    # 运行时配置（由 daemon/config/ 同步而来）
├── daemon/                    # NodeDaemon 源码、脚本、BPF 程序
├── dependencies/              # etcd / influxdb / code-server 的 Docker 构建目录
├── container-base/            # 卫星节点、地面站节点的镜像模板
├── TopoConfigurators/         # Python SDK 及示例拓扑控制器
├── tools/                     # 实用脚本（命名空间生成器、抓包工具等）
├── example/test_topologies/   # 参考仿真配置与拓扑文件
└── ui/                        # React Web 控制台
```

## 2. 主机依赖

1. **操作系统**：Ubuntu（我们在 22.04 上验证；内核参数每次重启都需重新设置）。
2. **Docker Engine**：版本 `24.0.5`。可通过 `sudo apt install docker.io` 安装，或参考官方文档。
3. **Go**：>= 1.20（Makefile 中使用 `go -C` 特性）。
4. **Python 3**：TopoConfigurator 及 CodeServer 构建脚本需要。
5. **sudo 权限**：访问 Docker socket 与修改内核参数都需要 root。

## 3. 内核参数（对应 readme_zh.md 第 4.1 节）

每次重启后执行以下命令，确保 inotify 数量与 ARP 回收阈值足够：

```bash
sudo sh -c 'echo 4096 > /proc/sys/fs/inotify/max_user_instances'
sudo sh -c 'echo 8192 > /proc/sys/net/ipv4/neigh/default/gc_thresh1'
sudo sh -c 'echo 16384 > /proc/sys/net/ipv4/neigh/default/gc_thresh2'
sudo sh -c 'echo 32768 > /proc/sys/net/ipv4/neigh/default/gc_thresh3'
```

如需持久化，可写入 `/etc/sysctl.d/*.conf`。

## 4. 依赖镜像（Etcd / InfluxDB / CodeServer）

我们在 `dependencies/custom-codeserver/Dockerfile` 中删除了 `SUDO_PASSWORD` 相关的 `ARG/ENV`，以消除 `SecretsUsedInArgOrEnv` 的构建警告。若运行时需要该变量，可在 `docker run` 时通过 `-e SUDO_PASSWORD=...` 注入。

构建三种依赖镜像并导出：

```bash
cd dependencies
make build      # 依次构建，最终生成 opensn_*.tar.gz
cd -
```

生成的压缩包包括：
- `opensn_etcd.tar.gz`
- `opensn_influxdb.tar.gz`
- `opensn_codeserver.tar.gz`

如需在另一台机器加载镜像：

```bash
docker load -i dependencies/opensn_etcd.tar.gz
docker load -i dependencies/opensn_influxdb.tar.gz
docker load -i dependencies/opensn_codeserver.tar.gz
```

## 5. 启动依赖容器

执行脚本可自动停止旧容器并以标准端口重新拉起：

```bash
bash daemon/scripts/start_depend_service.sh
```

示例输出：

```
opensn_etcd
opensn_influxdb
opensn_codeserver
3dae...  # etcd 容器 ID
9338...  # influxdb 容器 ID
7b90...  # code-server 容器 ID
```

使用 `docker ps` 验证端口映射：

```
CONTAINER ID   IMAGE                       PORTS
7b90...        realssd/opensn_codeserver   0.0.0.0:8079->8443/tcp
9338...        realssd/opensn_influxdb     0.0.0.0:8086->8086/tcp
3dae...        realssd/opensn_etcd         0.0.0.0:2379->2379/tcp
```

## 6. 构建 NodeDaemon

在仓库根目录运行：

```bash
make node-daemon
make sync-config   # 同步 daemon/config/config.json -> config/config.json
```

完成后，`NodeDaemon` 可执行文件位于仓库根目录，运行时配置存放于 `config/`。

## 7. 运行时配置（config/config.json）

相较默认模板，我们做了以下修改：

```json
{
  "app": {
    "is_servant": false,
    "master_address": "192.168.1.129",
    "listen_port": 8080,
    "enable_monitor": true,
    "enable_code_server": true,
    "interface_name": "ens33",            // 需改成宿主机真实网卡名
    "debug": false,
    "instance_capacity": 100,               // 统一限制为 100 颗卫星节点
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

请根据实际网络（IP、端口、网卡名）进行调整。若部署从节点，将 `is_servant` 设为 `true`，并把 `master_address` 指向主节点的地址。

## 8. 启动 NodeDaemon

需要 root 权限以管理 Docker 与网络命名空间：

```bash
sudo ./NodeDaemon
```

示例日志：

```
[INFO] Init Config Success, Config is {{false 192.168.1.129 ens33 8080 true true false 100 1 64} {...}}
[INFO] Run InstanceManage Module.
[INFO] Run Link Manager Module.
...
[INFO] Run MonitorModule Module.
[GIN-debug] [WARNING] Running in "debug" mode...
```

若需生产模式，启动前设置 `GIN_MODE=release` 或在代码中调用 `gin.SetMode(gin.ReleaseMode)`。

## 9. 访问 Web 控制台

在浏览器访问 `http://192.168.1.129:8080`（根据配置替换地址/端口），可进行以下操作：

1. 上传 `example/test_topologies/` 中的仿真配置与拓扑 JSON；
2. 观察日志等待拓扑加载完成；
3. 点击 **Start** 启动模拟；
4. 在 CodeServer (`docker exec -it opensn_codeserver bash`) 或本地运行 Topology Configurator；
5. 利用 3D 地图、节点详情、WebShell、抓包等功能进行调试。

## 10. 拓扑控制器要点

- 示例控制器：`TopoConfigurators/Standard/main.py`
- Python SDK：`TopoConfigurators/opensn/`
- 依赖安装：`pip install -r TopoConfigurators/opensn/requirements.txt`
- 控制器通过 Etcd / InfluxDB 与 NodeDaemon 交互，实现节点、链路和地理位置等对象的统一管理。

## 11. 维护与常见问题

- **重启依赖**：重新执行 `bash daemon/scripts/start_depend_service.sh`。
- **环境清理**：`bash daemon/scripts/delete_link_prefix.sh` 清理残留容器/链路。
- **配置变更**：若修改了 `daemon/config/config.json`，再次运行 `make sync-config` 保持同步。
- **内核参数丢失**：重启后重新执行第 3 节的命令。
- **横向扩容**：在多台机器复制 `NodeDaemon` 和配置，修改 `interface_name`，从节点 `is_servant=true`，`master_address` 指向主节点。

## 12. 命令速查表

| 步骤 | 命令 |
| ---- | ---- |
| 内核调优 | `sudo sh -c 'echo ...'`（四条命令） |
| 构建依赖镜像 | `cd dependencies && make build` |
| 加载镜像（可选） | `docker load -i dependencies/opensn_*.tar.gz` |
| 启动依赖容器 | `bash daemon/scripts/start_depend_service.sh` |
| 构建 NodeDaemon | `make node-daemon` |
| 同步配置 | `make sync-config` |
| 启动 NodeDaemon | `sudo ./NodeDaemon` |
| 打开 Web 控制台 | `http://<master_addr>:<listen_port>` |

完成以上步骤后，OpenSN 的依赖、守护进程与 Web 控制台即可在单机环境下顺利运行，设置与配置与本次验证保持一致。
