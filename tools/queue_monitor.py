import subprocess
import re
import time
import redis
import logging

# 使用 INFO 级别，避免日志刷屏，但保留核心状态可见
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

try:
    r = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True, socket_timeout=2.0)
    r.ping()
    logging.info("Redis 连通性测试: 成功！")
except Exception as e:
    logging.error(f"Redis 连接失败: {e}")
    exit(1)

def get_containers():
    """获取所有正在运行的 Docker 容器名称"""
    try:
        output = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True)
        # 只提取有意义的容器名，排除空行
        return [name.strip() for name in output.split('\n') if name.strip()]
    except Exception as e:
        logging.error(f"无法获取 Docker 容器列表: {e}")
        return []

def collect_queues():
    containers = get_containers()
    active_nodes = 0
    
    for container in containers:
        redis_key = f"telemetry:queue:{container}"
        try:
            # 核心魔法：从宿主机向容器内部发射 tc 命令
            cmd = ["docker", "exec", container, "tc", "-s", "qdisc", "show"]
            # 加上 1秒超时，绝对不会再卡死
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=1.0)
            current_queues = {}
            
            # 按 qdisc 块分割输出，因为一个节点有多个网卡
            blocks = output.split('qdisc ')
            for block in blocks:
                if 'dev ' in block and 'backlog ' in block:
                    # 正则提取真实的容器内网卡名 (例如 eth1)
                    iface_match = re.search(r'dev\s+(\S+)', block)
                    # 正则提取字节数
                    backlog_match = re.search(r'backlog\s+(\d+)[bB]', block)
                    
                    if iface_match and backlog_match:
                        iface = iface_match.group(1)
                        if iface == 'lo': continue # 忽略本地回环
                        
                        backlog = int(backlog_match.group(1))

                        current_queues[iface] = backlog

            # 每轮覆盖该节点的队列快照，避免接口消失后旧字段继续误导 Lyapunov。
            pipe = r.pipeline()
            pipe.delete(redis_key)
            if current_queues:
                pipe.hset(redis_key, mapping=current_queues)
                pipe.expire(redis_key, 5)
            pipe.execute()
            
            active_nodes += 1
                        
        except subprocess.TimeoutExpired:
            # 如果某个容器不响应，跳过，不影响全局
            pass
        except subprocess.CalledProcessError:
            # 有些容器可能没有 tc 命令或者不是卫星节点，默默忽略
            pass
        except Exception:
            pass

    logging.info(f"本轮采集完毕：成功扫描 {active_nodes}/{len(containers)} 个容器。")

if __name__ == '__main__':
    logging.info("集中式 Docker 队列探针 (Host-based) 启动...")
    while True:
        collect_queues()
        time.sleep(1) # 每秒扫描一次全网
