import streamlit as st
import folium
from streamlit_folium import st_folium, folium_static
import pandas as pd
import time
from datetime import datetime, timedelta
import json
import os
import math

# ===================== 坐标系转换（WGS84 <-> GCJ02）=====================
PI = 3.14159265358979323846
A = 6378245.0
EE = 0.00669342162296594323

def wgs84_to_gcj02(lat, lon):
    if out_of_china(lat, lon):
        return lat, lon
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return lat + dlat, lon + dlon

def gcj02_to_wgs84(lat, lon):
    if out_of_china(lat, lon):
        return lat, lon
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return lat - dlat, lon - dlon

def out_of_china(lat, lon):
    return not (72.004 <= lon <= 137.8347 and 18.0 <= lat <= 55.8271)

def transform_lat(lon, lat):
    ret = -100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat + 0.1 * lon * lat + 0.2 * math.sqrt(math.fabs(lon))
    ret += (20.0 * math.sin(6.0 * lon * PI) + 20.0 * math.sin(2.0 * lon * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 * math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret

def transform_lon(lon, lat):
    ret = 300.0 + lon + 2.0 * lat + 0.1 * lon * lon + 0.1 * lon * lat + 0.1 * math.sqrt(math.fabs(lon))
    ret += (20.0 * math.sin(6.0 * lon * PI) + 20.0 * math.sin(2.0 * lon * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lon * PI) + 40.0 * math.sin(lon / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lon / 12.0 * PI) + 300.0 * math.sin(lon / 30.0 * PI)) * 2.0 / 3.0
    return ret

# ===================== 障碍物持久化 =====================
OBSTACLE_FILE = "obstacle_config.json"

def save_obstacles(obstacles):
    with open(OBSTACLE_FILE, "w", encoding="utf-8") as f:
        json.dump(obstacles, f, ensure_ascii=False, indent=2)

def load_obstacles():
    if os.path.exists(OBSTACLE_FILE):
        with open(OBSTACLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# ===================== 绕行算法辅助函数 =====================
def point_distance(p1, p2):
    return math.hypot(p1[0]-p2[0], p1[1]-p2[1])

def get_obstacle_circle(obs):
    if obs["type"] == "circle":
        center = tuple(obs["center"])
        radius = obs["radius"]
    elif obs["type"] == "polygon":
        coords = obs["coordinates"]
        cx = sum(p[0] for p in coords) / len(coords)
        cy = sum(p[1] for p in coords) / len(coords)
        center = (cx, cy)
        radius = max(point_distance(center, (p[0], p[1])) for p in coords)
    elif obs["type"] == "rectangle":
        bounds = obs["bounds"]
        lat_min = min(bounds[0][0], bounds[1][0])
        lat_max = max(bounds[0][0], bounds[1][0])
        lon_min = min(bounds[0][1], bounds[1][1])
        lon_max = max(bounds[0][1], bounds[1][1])
        center = ((lat_min+lat_max)/2, (lon_min+lon_max)/2)
        radius = max(point_distance(center, (lat_min, lon_min)),
                     point_distance(center, (lat_min, lon_max)),
                     point_distance(center, (lat_max, lon_min)),
                     point_distance(center, (lat_max, lon_max)))
    else:
        return None
    return {"center": center, "radius": radius}

def circle_line_intersection(p1, p2, center, radius):
    x1, y1 = p1
    x2, y2 = p2
    cx, cy = center
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy
    a = dx*dx + dy*dy
    if a == 0:
        return point_distance(p1, center) <= radius
    b = 2*(fx*dx + fy*dy)
    c = fx*fx + fy*fy - radius*radius
    disc = b*b - 4*a*c
    if disc < 0:
        return False
    sqrt_disc = math.sqrt(disc)
    t1 = (-b - sqrt_disc) / (2*a)
    t2 = (-b + sqrt_disc) / (2*a)
    return (0 <= t1 <= 1) or (0 <= t2 <= 1)

def get_bypass_point(p1, p2, center, radius, side, safe_radius):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return center
    ux = dx / length
    uy = dy / length
    if side == 'left':
        perp_x = -uy
        perp_y = ux
    else:
        perp_x = uy
        perp_y = -ux
    offset = radius + safe_radius
    bypass_lat = center[0] + perp_x * offset
    bypass_lon = center[1] + perp_y * offset
    return (bypass_lat, bypass_lon)

def generate_route(obstacles, start, end, drone_height, safe_radius, strategy):
    conflict_circles = []
    for obs in obstacles:
        if obs.get("height", 0) >= drone_height:
            circle = get_obstacle_circle(obs)
            if circle:
                conflict_circles.append(circle)
    if not conflict_circles:
        return [start, end]
    conflict_circles.sort(key=lambda c: point_distance(start, c["center"]))
    route = [start]
    current_start = start
    current_end = end
    used = []
    max_iter = 20
    for _ in range(max_iter):
        hit = None
        for circ in conflict_circles:
            if circ in used:
                continue
            if circle_line_intersection(current_start, current_end, circ["center"], circ["radius"] + safe_radius):
                hit = circ
                break
        if hit is None:
            break
        if strategy == 'best':
            left_pt = get_bypass_point(current_start, current_end, hit["center"], hit["radius"], 'left', safe_radius)
            right_pt = get_bypass_point(current_start, current_end, hit["center"], hit["radius"], 'right', safe_radius)
            dist_left = point_distance(current_start, left_pt) + point_distance(left_pt, current_end)
            dist_right = point_distance(current_start, right_pt) + point_distance(right_pt, current_end)
            side = 'left' if dist_left <= dist_right else 'right'
        else:
            side = strategy
        bypass = get_bypass_point(current_start, current_end, hit["center"], hit["radius"], side, safe_radius)
        route.append(bypass)
        current_start = bypass
        used.append(hit)
    route.append(current_end)
    cleaned = [route[0]]
    for p in route[1:]:
        if point_distance(cleaned[-1], p) > 1e-6:
            cleaned.append(p)
    return cleaned

# ===================== 飞行模拟与通信日志 =====================
def format_time(seconds):
    return f"{int(seconds//60):02d}:{int(seconds%60):02d}"

def add_comm_log(message, source, target):
    """添加通信日志条目"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "时间戳": timestamp,
        "来源": source,
        "目标": target,
        "内容": message
    }
    if "comm_logs" not in st.session_state:
        st.session_state["comm_logs"] = []
    st.session_state["comm_logs"].insert(0, log_entry)  # 最新消息在前
    # 保留最近100条
    if len(st.session_state["comm_logs"]) > 100:
        st.session_state["comm_logs"] = st.session_state["comm_logs"][:100]

def update_flight():
    """模拟飞行状态更新，并自动记录通信日志"""
    if not st.session_state.get("flight_active", False):
        return
    route = st.session_state.get("flight_route", [])
    if not route or len(route) < 2:
        return
    speed = st.session_state.get("flight_speed", 8.5)
    current_idx = st.session_state.get("current_waypoint_idx", 0)
    if current_idx >= len(route) - 1:
        # 任务完成
        st.session_state["flight_active"] = False
        st.session_state["flight_paused"] = False
        st.session_state["task_status"] = "已完成"
        add_comm_log("MISSION_COMPLETE", "FCU", "GCS")
        return
    current_pos = st.session_state.get("current_position", route[0])
    target_pos = route[current_idx + 1]
    dist_to_target = point_distance(current_pos, target_pos) * 111320
    dt = 0.5
    move_dist = speed * dt
    if move_dist >= dist_to_target:
        # 到达下一个航点
        st.session_state["current_position"] = target_pos
        st.session_state["current_waypoint_idx"] += 1
        st.session_state["elapsed_time"] += dt
        st.session_state["remaining_distance"] = calculate_remaining_distance()
        st.session_state["battery"] = max(0, st.session_state["battery"] - 0.5)
        # 更新预计到达时间
        if st.session_state["remaining_distance"] > 0:
            eta_seconds = st.session_state["remaining_distance"] / speed
            st.session_state["eta"] = datetime.now() + timedelta(seconds=eta_seconds)
        else:
            st.session_state["eta"] = datetime.now()
        # 记录航点到达日志
        wp_num = st.session_state["current_waypoint_idx"]
        total_wp = len(route)
        add_comm_log(f"WP_REACHED #{wp_num} of {total_wp}", "FCU", "GCS")
        # 如果完成，下一次循环会触发 MISSION_COMPLETE
    else:
        ratio = move_dist / dist_to_target
        new_lat = current_pos[0] + (target_pos[0] - current_pos[0]) * ratio
        new_lon = current_pos[1] + (target_pos[1] - current_pos[1]) * ratio
        st.session_state["current_position"] = (new_lat, new_lon)
        st.session_state["elapsed_time"] += dt
        st.session_state["remaining_distance"] = calculate_remaining_distance()
        st.session_state["battery"] = max(0, st.session_state["battery"] - 0.5)
        if st.session_state["remaining_distance"] > 0:
            eta_seconds = st.session_state["remaining_distance"] / speed
            st.session_state["eta"] = datetime.now() + timedelta(seconds=eta_seconds)
        else:
            st.session_state["eta"] = datetime.now()

def calculate_remaining_distance():
    route = st.session_state.get("flight_route", [])
    current_idx = st.session_state.get("current_waypoint_idx", 0)
    current_pos = st.session_state.get("current_position", route[0] if route else None)
    if not route or current_pos is None:
        return 0.0
    total_dist = 0.0
    if current_idx < len(route) - 1:
        total_dist += point_distance(current_pos, route[current_idx + 1]) * 111320
    for i in range(current_idx + 1, len(route) - 1):
        total_dist += point_distance(route[i], route[i+1]) * 111320
    return total_dist

def start_flight():
    """开始飞行任务，初始化并记录日志"""
    route = st.session_state.get("flight_route")
    if route and len(route) >= 2:
        st.session_state["flight_active"] = True
        st.session_state["flight_paused"] = False
        st.session_state["task_status"] = "执行中"
        if st.session_state["current_waypoint_idx"] == 0 and st.session_state["elapsed_time"] == 0:
            st.session_state["current_position"] = route[0]
            st.session_state["remaining_distance"] = calculate_remaining_distance()
            add_comm_log("Mode: AUTO", "GCS", "FCU")
            add_comm_log("ACK", "FCU", "GCS")

# ===================== 页面初始化 =====================
st.set_page_config(page_title="无人机智能飞行系统", layout="wide")

if "page" not in st.session_state:
    st.session_state["page"] = "航线规划"
if "heartbeat_data" not in st.session_state:
    st.session_state["heartbeat_data"] = []
if "status" not in st.session_state:
    st.session_state["status"] = "正常运行"
if "monitor_running" not in st.session_state:
    st.session_state["monitor_running"] = False
if "start_point" not in st.session_state:
    st.session_state["start_point"] = {"lat": 32.2341, "lon": 118.7420}
if "end_point" not in st.session_state:
    st.session_state["end_point"] = {"lat": 32.2343, "lon": 118.7430}
if "obstacles" not in st.session_state:
    st.session_state["obstacles"] = load_obstacles()
if "drone_height" not in st.session_state:
    st.session_state["drone_height"] = 20.0
if "safe_radius" not in st.session_state:
    st.session_state["safe_radius"] = 5.0
if "planned_route" not in st.session_state:
    st.session_state["planned_route"] = None
if "flight_route" not in st.session_state:
    st.session_state["flight_route"] = None
# 飞行任务状态
if "flight_active" not in st.session_state:
    st.session_state["flight_active"] = False
if "flight_paused" not in st.session_state:
    st.session_state["flight_paused"] = False
if "task_status" not in st.session_state:
    st.session_state["task_status"] = "未开始"
if "current_waypoint_idx" not in st.session_state:
    st.session_state["current_waypoint_idx"] = 0
if "current_position" not in st.session_state:
    st.session_state["current_position"] = None
if "elapsed_time" not in st.session_state:
    st.session_state["elapsed_time"] = 0.0
if "remaining_distance" not in st.session_state:
    st.session_state["remaining_distance"] = 0.0
if "battery" not in st.session_state:
    st.session_state["battery"] = 100.0
if "flight_speed" not in st.session_state:
    st.session_state["flight_speed"] = 8.5
if "eta" not in st.session_state:
    st.session_state["eta"] = datetime.now()
if "comm_logs" not in st.session_state:
    st.session_state["comm_logs"] = []

# ===================== 侧边栏 =====================
with st.sidebar:
    st.title("功能导航")
    if st.button("✈️ 航线规划", use_container_width=True):
        st.session_state["page"] = "航线规划"
        st.session_state["monitor_running"] = False
        st.session_state["flight_active"] = False
    if st.button("📡 飞行监控", use_container_width=True):
        st.session_state["page"] = "飞行监控"
        st.session_state["monitor_running"] = False
        if st.session_state.get("planned_route") and st.session_state.get("flight_route") is None:
            st.session_state["flight_route"] = st.session_state["planned_route"]
            st.session_state["current_position"] = st.session_state["flight_route"][0]
            st.session_state["remaining_distance"] = calculate_remaining_distance()
            # 清空旧日志
            st.session_state["comm_logs"] = []
    st.divider()
    st.subheader("坐标系设置")
    coord_choice = st.radio("坐标制式", ["WGS-84", "GCJ-02"], index=1, key="coord_choice")
    st.info(f"当前已保存障碍物：{len(st.session_state['obstacles'])} 处")

# ===================== 航线规划页面 =====================
if st.session_state["page"] == "航线规划":
    st.title("✈️ 航线规划（高度检测与智能绕行）")
    col1, col2 = st.columns([3, 1])

    with col1:
        center_gcj = wgs84_to_gcj02(32.2341, 118.7420)
        m = folium.Map(location=center_gcj, zoom_start=18,
                       tiles="https://webst02.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
                       attr="高德地图")
        start_gcj = wgs84_to_gcj02(st.session_state["start_point"]["lat"], st.session_state["start_point"]["lon"])
        end_gcj = wgs84_to_gcj02(st.session_state["end_point"]["lat"], st.session_state["end_point"]["lon"])
        folium.Marker(start_gcj, popup="起点", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker(end_gcj, popup="终点", icon=folium.Icon(color="green")).add_to(m)
        folium.PolyLine([start_gcj, end_gcj], color="blue", weight=2, dash_array="5,5").add_to(m)

        for obs in st.session_state["obstacles"]:
            h = obs["height"]
            if obs["type"] == "polygon":
                pts = [wgs84_to_gcj02(p[0], p[1]) for p in obs["coordinates"]]
                folium.Polygon(locations=pts, color="red", fill=True, fill_opacity=0.4,
                               popup=f"障碍物高度：{h} 米").add_to(m)
            elif obs["type"] == "rectangle":
                bounds = [wgs84_to_gcj02(p[0], p[1]) for p in obs["bounds"]]
                folium.Rectangle(bounds=bounds, color="red", fill=True, fill_opacity=0.4,
                                 popup=f"障碍物高度：{h} 米").add_to(m)
            elif obs["type"] == "circle":
                c_pt = wgs84_to_gcj02(obs["center"][0], obs["center"][1])
                folium.Circle(location=c_pt, radius=obs["radius"], color="red",
                              fill=True, fill_opacity=0.4, popup=f"障碍物高度：{h} 米").add_to(m)

        if st.session_state["planned_route"]:
            route_gcj = [wgs84_to_gcj02(lat, lon) for lat, lon in st.session_state["planned_route"]]
            folium.PolyLine(route_gcj, color="green", weight=4, opacity=0.8, popup="规划航线").add_to(m)
            for pt in route_gcj[1:-1]:
                folium.CircleMarker(pt, radius=4, color="green", fill=True).add_to(m)

        draw = folium.plugins.Draw(export=True,
                                   draw_options={"polyline": False, "rectangle": True, "polygon": True, "circle": True, "marker": False})
        draw.add_to(m)
        map_data = st_folium(m, width=850, height=620, returned_objects=["last_active_drawing"])

    with col2:
        st.subheader("起止航点设置")
        st.number_input("起点纬度", value=st.session_state["start_point"]["lat"], format="%.4f", disabled=True)
        st.number_input("起点经度", value=st.session_state["start_point"]["lon"], format="%.4f", disabled=True)
        st.number_input("终点纬度", value=st.session_state["end_point"]["lat"], format="%.4f", disabled=True)
        st.number_input("终点经度", value=st.session_state["end_point"]["lon"], format="%.4f", disabled=True)

        st.divider()
        st.subheader("飞行参数")
        new_height = st.number_input("飞行高度（米）", min_value=1.0, max_value=500.0, value=st.session_state["drone_height"])
        new_radius = st.number_input("安全规避半径（米）", min_value=1.0, max_value=30.0, value=st.session_state["safe_radius"])
        st.session_state["drone_height"] = new_height
        st.session_state["safe_radius"] = new_radius

        st.divider()
        st.subheader("障碍物管理")
        obs_height = st.number_input("障碍物高度（米）", min_value=1.0, max_value=500.0, value=15.0)
        st.write("1. 在地图上绘制障碍物区域（多边形/矩形/圆形）")
        st.write("2. 填写实际高度")
        st.write("3. 点击「添加此障碍物」保存")

        if st.button("➕ 添加此障碍物", type="primary"):
            draw_data = map_data.get("last_active_drawing")
            if not draw_data:
                st.warning("请先在地图上绘制一个障碍物区域")
            else:
                geo = draw_data["geometry"]
                new_obs = None
                if geo["type"] == "Polygon":
                    coords = [gcj02_to_wgs84(p[1], p[0]) for p in geo["coordinates"][0]]
                    new_obs = {"type": "polygon", "coordinates": coords, "height": obs_height}
                elif geo["type"] == "Rectangle":
                    pts = [gcj02_to_wgs84(p[1], p[0]) for p in geo["coordinates"][0]]
                    if len(pts) >= 2:
                        bounds = [pts[0], pts[2]] if len(pts) >= 3 else [pts[0], pts[1]]
                        new_obs = {"type": "rectangle", "bounds": bounds, "height": obs_height}
                elif geo["type"] == "Circle":
                    lat, lon = gcj02_to_wgs84(geo["coordinates"][1], geo["coordinates"][0])
                    new_obs = {"type": "circle", "center": [lat, lon],
                               "radius": draw_data["properties"]["radius"], "height": obs_height}
                if new_obs:
                    st.session_state["obstacles"].append(new_obs)
                    save_obstacles(st.session_state["obstacles"])
                    st.success(f"障碍物已添加，当前共 {len(st.session_state['obstacles'])} 个")
                    st.rerun()

        if st.button("💾 一键保存全部障碍物到 JSON"):
            save_obstacles(st.session_state["obstacles"])
            st.success(f"已保存 {len(st.session_state['obstacles'])} 个障碍物到 {OBSTACLE_FILE}")

        if st.button("🗑️ 清空全部障碍物"):
            st.session_state["obstacles"] = []
            save_obstacles([])
            st.session_state["planned_route"] = None
            st.warning("所有障碍物已清空")
            st.rerun()

        st.divider()
        st.subheader("智能航线生成")
        route_strategy = st.selectbox("绕行策略", ["向左绕行", "向右绕行", "最佳航线"])
        strategy_map = {"向左绕行": "left", "向右绕行": "right", "最佳航线": "best"}

        if st.button("生成规划航线", type="primary"):
            drone_h = st.session_state["drone_height"]
            safe_r = st.session_state["safe_radius"]
            obs_list = st.session_state["obstacles"]
            start_pt = (st.session_state["start_point"]["lat"], st.session_state["start_point"]["lon"])
            end_pt = (st.session_state["end_point"]["lat"], st.session_state["end_point"]["lon"])

            if not obs_list:
                st.success("✅ 无障碍物，允许直线飞行")
                st.session_state["planned_route"] = [start_pt, end_pt]
            else:
                conflict = any(o["height"] >= drone_h for o in obs_list)
                if conflict:
                    st.warning("⚠️ 检测到障碍物高度 ≥ 飞行高度，正在生成绕行航线...")
                    route = generate_route(obs_list, start_pt, end_pt, drone_h, safe_r, strategy_map[route_strategy])
                    st.session_state["planned_route"] = route
                    st.success(f"航线生成成功，共 {len(route)} 个航点（绿色线）")
                else:
                    st.success("✅ 飞行高度充足，无碰撞风险，直线飞行")
                    st.session_state["planned_route"] = [start_pt, end_pt]
            st.rerun()

        if st.session_state["planned_route"]:
            st.info(f"当前航线包含 {len(st.session_state['planned_route'])} 个航点")

# ===================== 飞行监控页面（含通信拓扑与日志）======================
elif st.session_state["page"] == "飞行监控":
    st.title("📡 飞行实时画面 - 任务执行监控")
    
    # 任务控制栏
    col_btn1, col_btn2, col_btn3, col_btn4, col_status = st.columns([1,1,1,1,2])
    with col_btn1:
        if st.button("开始任务", use_container_width=True):
            if st.session_state.get("flight_route") and len(st.session_state["flight_route"]) >= 2:
                start_flight()
            else:
                st.warning("请先在航线规划页面生成航线")
    with col_btn2:
        if st.button("暂停", use_container_width=True):
            st.session_state["flight_active"] = False
            st.session_state["flight_paused"] = True
            st.session_state["task_status"] = "已暂停"
            add_comm_log("PAUSE", "GCS", "FCU")
    with col_btn3:
        if st.button("停止", use_container_width=True):
            st.session_state["flight_active"] = False
            st.session_state["flight_paused"] = False
            st.session_state["task_status"] = "已停止"
            add_comm_log("STOP", "GCS", "FCU")
    with col_btn4:
        if st.button("重置", use_container_width=True):
            st.session_state["flight_active"] = False
            st.session_state["flight_paused"] = False
            st.session_state["task_status"] = "未开始"
            st.session_state["current_waypoint_idx"] = 0
            if st.session_state.get("flight_route"):
                st.session_state["current_position"] = st.session_state["flight_route"][0]
            st.session_state["elapsed_time"] = 0.0
            st.session_state["remaining_distance"] = calculate_remaining_distance()
            st.session_state["battery"] = 100.0
            st.session_state["eta"] = datetime.now()
            st.session_state["comm_logs"] = []
            add_comm_log("System reset", "GCS", "OBC")
    with col_status:
        st.info(f"状态：{st.session_state['task_status']}")
    
    # 飞行参数仪表板
    col_metrics1, col_metrics2, col_metrics3, col_metrics4, col_metrics5, col_metrics6 = st.columns(6)
    route_len = len(st.session_state["flight_route"]) if st.session_state.get("flight_route") else 0
    current_wp = st.session_state.get("current_waypoint_idx", 0) + 1 if route_len > 0 else 0
    with col_metrics1:
        st.metric("当前航点", f"{current_wp}/{route_len}")
    with col_metrics2:
        speed = st.number_input("飞行速度 (m/s)", min_value=1.0, max_value=20.0, value=st.session_state["flight_speed"], step=0.5, key="speed_input")
        st.session_state["flight_speed"] = speed
        st.metric("飞行速度", f"{speed:.1f} m/s")
    with col_metrics3:
        elapsed = st.session_state.get("elapsed_time", 0.0)
        st.metric("已用时间", format_time(elapsed))
    with col_metrics4:
        rem_dist = st.session_state.get("remaining_distance", 0.0)
        st.metric("剩余距离", f"{rem_dist:.0f} m")
    with col_metrics5:
        eta = st.session_state.get("eta", datetime.now())
        eta_str = eta.strftime("%H:%M:%S") if eta > datetime.now() else "00:00:00"
        st.metric("预计到达", eta_str)
    with col_metrics6:
        battery = st.session_state.get("battery", 100.0)
        st.metric("电量模拟", f"{battery:.0f}%")
    
    # 实时地图 + 通信拓扑和日志（左右布局）
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader("实时飞行地图")
        if st.session_state.get("flight_route"):
            center_gcj = wgs84_to_gcj02(32.2341, 118.7420)
            m2 = folium.Map(location=center_gcj, zoom_start=18,
                           tiles="https://webst02.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
                           attr="高德地图")
            route_gcj = [wgs84_to_gcj02(lat, lon) for lat, lon in st.session_state["flight_route"]]
            folium.PolyLine(route_gcj, color="green", weight=4, opacity=0.8, popup="规划航线").add_to(m2)
            start_gcj = route_gcj[0]
            end_gcj = route_gcj[-1]
            folium.Marker(start_gcj, popup="起点", icon=folium.Icon(color="red")).add_to(m2)
            folium.Marker(end_gcj, popup="终点", icon=folium.Icon(color="green")).add_to(m2)
            for obs in st.session_state["obstacles"]:
                h = obs["height"]
                if obs["type"] == "polygon":
                    pts = [wgs84_to_gcj02(p[0], p[1]) for p in obs["coordinates"]]
                    folium.Polygon(locations=pts, color="red", fill=True, fill_opacity=0.4,
                                   popup=f"障碍物高度：{h} 米").add_to(m2)
                elif obs["type"] == "rectangle":
                    bounds = [wgs84_to_gcj02(p[0], p[1]) for p in obs["bounds"]]
                    folium.Rectangle(bounds=bounds, color="red", fill=True, fill_opacity=0.4,
                                     popup=f"障碍物高度：{h} 米").add_to(m2)
                elif obs["type"] == "circle":
                    c_pt = wgs84_to_gcj02(obs["center"][0], obs["center"][1])
                    folium.Circle(location=c_pt, radius=obs["radius"], color="red",
                                  fill=True, fill_opacity=0.4, popup=f"障碍物高度：{h} 米").add_to(m2)
            if st.session_state.get("current_position"):
                current_gcj = wgs84_to_gcj02(st.session_state["current_position"][0], st.session_state["current_position"][1])
                folium.Marker(current_gcj, popup="无人机当前位置", icon=folium.Icon(color="blue", icon="plane", prefix="fa")).add_to(m2)
                folium.Circle(current_gcj, radius=st.session_state["safe_radius"], color="blue", fill=False, weight=2).add_to(m2)
            folium_static(m2, width=600, height=400)
        else:
            st.info("请先在航线规划页面生成航线")
    
    with col_right:
        # 通信链路拓扑图（用HTML/CSS模拟）
        st.subheader("通信链路拓扑与数据流")
        topology_html = """
        <div style="background-color:#f0f2f6; border-radius:10px; padding:15px; text-align:center;">
            <div style="display:flex; justify-content:space-around; align-items:center; margin-bottom:20px;">
                <div style="background-color:#4CAF50; color:white; padding:10px 20px; border-radius:8px;">GCS 在线</div>
                <div style="font-size:24px;">→</div>
                <div style="background-color:#2196F3; color:white; padding:10px 20px; border-radius:8px;">OBC 在线</div>
                <div style="font-size:24px;">→</div>
                <div style="background-color:#FF9800; color:white; padding:10px 20px; border-radius:8px;">FCU 在线</div>
            </div>
            <div style="margin-top:10px; font-size:14px; color:#333;">
                <div>📡 GCS → OBC → FCU  (指令上行)</div>
                <div>📡 FCU → OBC → GCS  (遥测下行)</div>
            </div>
            <div style="margin-top:15px; background-color:#e9ecef; border-radius:8px; padding:8px;">
                <span>数据流状态：</span>
                <span style="color:green;">█</span> 遥测下行 正常 &nbsp;&nbsp;
                <span style="color:green;">█</span> 指令上行 正常 &nbsp;&nbsp;
                <span style="color:green;">█</span> 视频流 正常
            </div>
        </div>
        """
        st.markdown(topology_html, unsafe_allow_html=True)
        
        # 通信日志
        st.subheader("通信日志")
        if st.button("清空日志"):
            st.session_state["comm_logs"] = []
        if st.session_state.get("comm_logs"):
            log_df = pd.DataFrame(st.session_state["comm_logs"])
            # 重命名列以符合中文习惯
            log_df = log_df.rename(columns={"时间戳": "时间戳", "来源": "来源", "目标": "目标", "内容": "内容"})
            st.dataframe(log_df, use_container_width=True, height=300)
        else:
            st.info("暂无通信日志，开始飞行任务后将自动记录。")
    
    # 自动飞行更新循环
    if st.session_state.get("flight_active") and not st.session_state.get("flight_paused"):
        update_flight()
        time.sleep(0.5)
        st.rerun()
