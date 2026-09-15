from datetime import datetime
from type_model_def import EmulationTypeConfig, TopologyLink, TopologyInstance, TopologyConfig
from instance_types import EX_TLE0_KEY,EX_TLE1_KEY,EX_TLE2_KEY,EX_ORBIT_INDEX,EX_SATELLITE_INDEX,EX_LATITUDE_KEY,EX_LONGITUDE_KEY,EX_GROUND_INDEX,TYPE_GROUND_STATION,TYPE_SATELLITE,EX_AREA_KEY,EX_ALTITUDE_KEY
from address_type import LINK_V4_ADDR_KEY
import math
import random
import json

EARTH_MU_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.137

def mean_motion_from_altitude(altitude_km: float) -> float:
    a = EARTH_RADIUS_KM + altitude_km
    period_seconds = 2 * math.pi * math.sqrt(a ** 3 / EARTH_MU_KM3_S2)
    return 86400.0 / period_seconds
def get_year_day(now_time: datetime) -> (int, float):
    year = now_time.year
    day = float(now_time.microsecond)
    day /= 1000
    day += now_time.second
    day /= 60
    day += now_time.minute
    day /= 60
    day += now_time.hour
    day /= 24
    day += (now_time - datetime(year, 1, 1)).days

    return year % 100, day


def str_checksum(line: str) -> int:
    sum_num = 0
    for c in line:
        if c.isdigit():
            sum_num += int(c)
        elif c == '-':
            sum_num += 1
    return sum_num % 10


def area2line(y: int, x: int, x_limit: int, y_limit: int) -> int:
    y_true = (y + y_limit) % y_limit
    x_true = (x + x_limit) % x_limit
    return y_true * x_limit + x_true


def generate_tle(orbit_num: int, orbit_satellite_num: int, all_start_latitude, all_start_longitude, orbit_angle, delta_percent, period) -> (list, dict):
    satellites = []
    index_2d = []
    topo = {}
    freq = 1 / period
    line_1 = "1 00000U 23666A   %02d%012.8f  .00000000  00000-0 00000000 0 0000"
    line_2 = "2 00000  %02.4f %08.4f 0000011   0.0000 %8.4f %11.8f00000"
    year2, day = get_year_day(datetime(2026, 3, 20, 0, 0, 0))
    total_longitude = 180
    if abs(orbit_angle) < 80:
        total_longitude = 360
    delta = 360 / orbit_satellite_num * delta_percent
    for i in range(orbit_num):
        start_latitude = all_start_latitude + delta * i
        start_longitude = all_start_longitude + total_longitude * i / orbit_num
        index_1d = []
        for j in range(orbit_satellite_num):
            this_latitude = start_latitude + 360 * j / orbit_satellite_num
            this_line_1 = line_1 % (year2, day)
            this_line_2 = line_2 % (orbit_angle, start_longitude, this_latitude, freq)
            index_1d.append(len(satellites))
            satellites.append(
                [
                    "NODE_%d_%d" % (i, j),
                    this_line_1 + str(str_checksum(this_line_1)),
                    this_line_2 + str(str_checksum(this_line_2))
                ]
            )
        index_2d.append(index_1d)

    for i in range(len(satellites)):
        y = i // orbit_satellite_num
        x = i % orbit_satellite_num
        if orbit_satellite_num > 1:
            array = [index_2d[y][(x + 1) % orbit_satellite_num]]
        else:
            array = []
        if abs(orbit_angle) < 80 or y < orbit_num - 1:
            array.append(index_2d[(y + 1) % orbit_num][x])
        topo[str(i)] = array
    return satellites, topo

constellation_size_list = ["6x11","31x31","40x18","72x22","12x10","10x10"]

# 每个星座的可选覆盖：orbit_angle（轨道倾角，°）、altitude_km（轨道高度）、
# mean_motion（rev/day，未给 altitude 时使用）、ground_station_num（地面站数量）、
# ground_station_coords（固定地面站坐标列表，元素为 (lat, lon, alt_m)）
CONSTELLATION_CONFIG = {
    "6x11": {
        "orbit_angle": 55,
        "altitude_km": 508,
        "ground_station_num": 12,
        "ground_station_coords": [
            (39.9042, 116.4074, 50.0),     # Beijing
            (35.6762, 139.6503, 40.0),     # Tokyo
        ],
    },
}

if __name__ == "__main__":
    default_ground_station_num = 2
    default_orbit_angle = 90
    default_mean_motion = 13.1507
    emu_config :dict[str,EmulationTypeConfig] = {
        "Satellite": EmulationTypeConfig("docker.io/realssd/satellite-router", {}, "50M", "128M").__dict__,
        "GroundStation": EmulationTypeConfig("docker.io/realssd/ground-station", {}, "50M", "128M").__dict__
    }
    emu_config_file = open("emu_config.json", "w")
    emu_config_file.write(json.dumps(emu_config))
    emu_config_file.close()
    for constellation_size in constellation_size_list:
        cfg = CONSTELLATION_CONFIG.get(constellation_size, {})
        constellation_x = int(constellation_size.split('x')[0])
        constellation_y = int(constellation_size.split('x')[1])
        start_longitude = 0
        start_latitude = 0
        orbit_angle = cfg.get("orbit_angle", default_orbit_angle)
        ground_station_num = cfg.get("ground_station_num", default_ground_station_num)
        ground_station_coords = cfg.get("ground_station_coords")
        if "altitude_km" in cfg:
            mean_motion = mean_motion_from_altitude(cfg["altitude_km"])
        else:
            mean_motion = cfg.get("mean_motion", default_mean_motion)
        delta_percent = 1 / constellation_x
        period = 1 / mean_motion

        sat, topos = generate_tle(constellation_x, constellation_y, start_longitude, start_latitude, orbit_angle, delta_percent, period)
        node_grid = []
        for i in range(constellation_x):
            array = []
            for j in range(constellation_y):
                array.append(TopologyInstance(TYPE_SATELLITE, {
                    EX_TLE0_KEY: sat[area2line(i, j, constellation_y, constellation_x)][0],
                    EX_TLE1_KEY: sat[area2line(i, j, constellation_y, constellation_x)][1],
                    EX_TLE2_KEY: sat[area2line(i, j, constellation_y, constellation_x)][2],
                    EX_AREA_KEY:"0.0.0.0",
                    EX_ORBIT_INDEX: str(i),
                    EX_SATELLITE_INDEX: str(j),
                }))
            node_grid.append(array)
        links = []
        for l0_str,l1_list in topos.items():
            for l1 in l1_list:
                links.append(TopologyLink("vlink", [int(l0_str),l1],{},[{},{}],{}))

        topology_config = TopologyConfig()
        for i in range(constellation_x):
            for j in range(constellation_y):
                topology_config.instances.append(node_grid[i][j])

        for index in range(ground_station_num):
            if ground_station_coords is not None and index < len(ground_station_coords):
                lat, lon, alt = ground_station_coords[index]
            else:
                lat = random.random() * 180 - 90
                lon = random.random() * 360 - 180
                alt = random.random() * 10
            topology_config.instances.append(TopologyInstance(TYPE_GROUND_STATION, {
                    EX_GROUND_INDEX: str(index),
                    EX_LATITUDE_KEY: str(lat),
                    EX_LONGITUDE_KEY: str(lon),
                    EX_ALTITUDE_KEY: str(alt)
                })
            )

        for link in links:
            topology_config.links.append(link)

        topology_config_file = open("topology_config_%d_%d.json"%(constellation_x,constellation_y), "w")
        print(f"Generate topology_config_{constellation_x}_{constellation_y}.json")
        topology_config_file.write(topology_config.toJson())
        topology_config_file.close()