#!/bin/bash
set +e
sudo docker rm -f opensn_etcd
sudo docker rm -f opensn_influxdb
sudo docker rm -f opensn_codeserver
set -e
# Resolve repo root so config path works regardless of cwd
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_JSON="$REPO_ROOT/config/config.json"

# Extract master address and listen port from config
# Use host.docker.internal to reach host from containers (requires Docker 20.10+)
ADDR="host.docker.internal"
PORT=$(python3 -c "import json;print(json.load(open('$CONFIG_JSON'))['app']['listen_port'])")

sudo docker run -d --rm --name=opensn_etcd -p 2379:2379 realssd/opensn_etcd
sudo docker run -d --rm --name=opensn_influxdb  -p 8086:8086 realssd/opensn_influxdb
sudo docker run -d --rm --name=opensn_codeserver \
	-e ADDR="$ADDR" \
	-e PORT="$PORT" \
	--add-host host.docker.internal:host-gateway \
	-v "$REPO_ROOT/TopoConfigurators:/workspace" \
	--cpus=1 -m 1g -p 8079:8443 realssd/opensn_codeserver
