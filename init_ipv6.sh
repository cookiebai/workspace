#!/bin/bash
echo "开始为星地集群注入 IPv6 身份地址与基础路由..."

# 获取所有卫星和地面站容器
containers=$(docker ps --format "{{.Names}}" | grep -E "Satellite|GroundStation")
count=$(echo "$containers" | wc -l)
echo "发现 $count 个容器"

echo ""
echo "=== 第一阶段：收集容器信息 ==="

# 收集所有容器的 IPv4 地址（优先使用 eth0）
declare -A container_ips
first_container=""
for container in $containers; do
    node_id=$(echo $container | cut -d'_' -f2)
    ipv6_addr="fd00:${node_id:0:4}:${node_id:4:4}::1"

    # 优先使用 eth0 的 IPv4 地址
    ipv4_addr=$(docker exec $container sh -c "ip -4 addr show eth0 2>/dev/null | grep inet | head -1 | awk '{print \$2}' | cut -d'/' -f1" 2>/dev/null)

    # 如果 eth0 没有 IPv4，获取第一个非 lo 接口
    if [ -z "$ipv4_addr" ]; then
        iface=$(docker exec $container sh -c "ls /sys/class/net | grep -v lo | head -n 1" 2>/dev/null)
        ipv4_addr=$(docker exec $container sh -c "ip -4 addr show $iface 2>/dev/null | grep inet | head -1 | awk '{print \$2}' | cut -d'/' -f1" 2>/dev/null)
    fi

    if [ -z "$ipv4_addr" ]; then
        echo "⚠️ 跳过 $container: 缺少 IPv4"
        continue
    fi

    container_ips[$container]=$ipv4_addr
    if [ -z "$first_container" ]; then
        first_container=$container
    fi
done

echo "收集到 ${#container_ips[@]} 个容器 IPv4 地址"

echo ""
echo "=== 第二阶段：配置每个容器 ==="

# 获取第一个容器的 IPv4 作为 Hub 地址
if [ -n "$first_container" ]; then
    hub_ip=${container_ips[$first_container]}
    echo "Hub: $first_container ($hub_ip)"
fi

for container in $containers; do
    if [ -z "${container_ips[$container]}" ]; then
        continue
    fi

    ipv4_addr=${container_ips[$container]}
    node_id=$(echo $container | cut -d'_' -f2)
    ipv6_addr="fd00:${node_id:0:4}:${node_id:4:4}::1"

    # 获取第一个非 lo 接口
    iface=$(docker exec $container sh -c "ls /sys/class/net | grep -v lo | head -n 1" 2>/dev/null)

    echo ">>> 配置 $container..."

    # 1. 清理旧配置 - 先删除路由
    docker exec $container ip -6 route del fd00::/8 2>/dev/null || true

    # 2. 删除所有命名隧道（清理之前创建的）- 先做这个避免资源耗尽
    for t in $(docker exec $container ip tunnel show 2>/dev/null | grep -o 'srv6[^: ]*' 2>/dev/null); do
        docker exec $container ip tunnel del $t 2>/dev/null || true
    done

    # 3. 删除 srv6_tun
    docker exec $container ip tunnel del srv6_tun 2>/dev/null || true

    # 4. 配置身份地址 (Identity)
    docker exec $container ip -6 addr add $ipv6_addr/128 dev $iface 2>/dev/null || true

    # 5. 开启内核 IPv6 转发
    docker exec $container sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || true

    # 6. 删除 SRv6 encap 路由（干扰正常隧道）
    for route in $(docker exec $container ip -6 route show 2>/dev/null | grep "encap seg6" | awk '{print $1}'); do
        docker exec $container ip -6 route del $route 2>/dev/null || true
    done

    # 7. 创建点对点 IPv6-over-IPv4 隧道 (srv6_tun)
    # 如果是 Hub，使用第二个容器的 IP
    # 如果是其他容器，都指向 Hub
    if [ "$container" = "$first_container" ]; then
        # Hub: 连接到第二个容器
        remote_ip=""
        for target in $containers; do
            if [ "$target" != "$first_container" ] && [ -n "${container_ips[$target]}" ]; then
                remote_ip=${container_ips[$target]}
                break
            fi
        done
    else
        # 辐射节点: 连接到 Hub
        remote_ip=$hub_ip
    fi

    if [ -n "$remote_ip" ]; then
        docker exec $container ip tunnel add srv6_tun mode sit remote $remote_ip local $ipv4_addr ttl 64 2>/dev/null || true
        docker exec $container ip link set srv6_tun up 2>/dev/null || true
        docker exec $container ip link set srv6_tun mtu 1400 2>/dev/null || true
        docker exec $container ip -6 addr add ::$ipv4_addr/96 dev srv6_tun 2>/dev/null || true
    fi

    # 8. 添加 fd00::/8 路由通过隧道发出
    docker exec $container ip -6 route add fd00::/8 dev srv6_tun metric 1024 2>/dev/null || true

    # 9. 最后开启 seg6_enabled
    docker exec $container sysctl -w net.ipv6.conf.all.seg6_enabled=1 >/dev/null 2>&1 || true
    docker exec $container sysctl -w net.ipv6.conf.default.seg6_enabled=1 >/dev/null 2>&1 || true

    echo "✅ $container 配置完毕: IPv4=$ipv4_addr, IPv6=$ipv6_addr -> $remote_ip"
done

echo ""
echo "=== 第三阶段：配置 Hub 到所有容器的点对点隧道 ==="

if [ -n "$first_container" ]; then
    hub_ip=${container_ips[$first_container]}
    echo "Hub IP: $hub_ip"

    tunnel_idx=1
    for target in $containers; do
        if [ "$target" = "$first_container" ] || [ -z "${container_ips[$target]}" ]; then
            continue
        fi

        target_ip=${container_ips[$target]}
        tunnel_name="srv6_$(printf '%02d' $tunnel_idx)"

        echo "配置 $tunnel_name -> $target ($target_ip)..."
        docker exec $first_container ip tunnel del $tunnel_name 2>/dev/null || true
        docker exec $first_container ip tunnel add $tunnel_name mode sit remote $target_ip local $hub_ip ttl 64 2>/dev/null || true
        docker exec $first_container ip link set $tunnel_name up 2>/dev/null || true

        tunnel_idx=$((tunnel_idx + 1))
    done
fi

echo ""
echo "全网 IPv6-over-IPv4 隧道配置完成！"