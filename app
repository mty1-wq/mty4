import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import time
from datetime import datetime
import json
import os
import math

# ===================== 坐标系转换（WGS84 ↔ GCJ02）=====================
PI = 3.1415926535897932384626
A = 6378245.0
EE = 0.00669342162296594323

def wgs84_to_gcj02(lat, lon):
    if out_of_china(lat, lon):
        return lat, lon
    dlat = transformlat(lon - 105.0, lat - 35.0)
    dlon = transformlon(lon - 105.0, lat - 35.0)
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
    dlat = transformlat(lon - 105.0, lat - 35.0)
    dlon = transformlon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return lat - dlat, lon - dlon

def out_of_china(lat, lon):
    return not (72.004 <= lon <= 137.8347 and 18.0 <= lat <= 55.8271)

def transformlat(lon, lat):
    ret = -100.0 + 2.0*lon + 3.0*lat + 0.2*lat*lat + 0.1*lon*lat + 0.2*math.sqrt(math.fabs(lon))
    ret += (20.0*math.sin(6.0*lon*PI) + 20.0*math.sin(2.0*lon*PI)) * 2.0 / 3.0
    ret += (20.0*math.sin(lat*PI) + 40.0*math.sin(lat/3.0*PI)) * 2.0 / 3.0
    ret += (160.0*math.sin(lat/12.0*PI) + 320*math.sin(lat*PI/30.0)) * 2.0 / 3.0
    return ret

def transformlon(lon, lat):
    ret = 300.0 + lon + 2.0*lat + 0.1*lon*lon + 0.1*lon*lat + 0.1*math.sqrt(math.fabs(lon))
    ret += (20.0*math.sin(6.0*lon*PI) + 20.0*math.sin(2.0*lon*PI)) * 2.0 / 3.0
    ret += (20.0*math.sin(lon*PI) + 40.0*math.sin(lon/3.0*PI)) * 2.0 / 3.0
    ret += (150.0*math.sin(lon/12.0*PI) + 300.0*math.sin(lon/30.0*PI)) * 2.0 / 3.0
    return ret

# ===================== 障碍物持久化（含高度）=====================
OBSTACLE_FILE = "obstacle_config.json"

def save_obstacles(obstacles):
    with open(OBSTACLE_FILE, "w", encoding="utf-8") as f:
        json.dump(obstacles, f, ensure_ascii=False, indent=2)

def load_obstacles():
    if os.path.exists(OBSTACLE_FILE):
        with open(OBSTACLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# ===================== 页面初始化 =====================
st.set_page_config(page_title="无人机智能化应用Demo", layout="wide")

if "page" not in st.session_state:
    st.session_state["page"] = "航线规划"
if "heartbeat_data" not in st.session_state:
    st.session_state["heartbeat_data"] = []
if "status" not in st.session_state:
    st.session_state["status"] = "正常运行"
if "start_point" not in st.session_state:
    st.session_state["start_point"] = {"lat": 32.2323, "lon": 118.749}
if "end_point" not in st.session_state:
    st.session_state["end_point"] = {"lat": 32.2344, "lon": 118.749}
if "obstacles" not in st.session_state:
    st.session_state["obstacles"] = load_obstacles()
if "drone_height" not in st.session_state:
    st.session_state["drone_height"] = 20.0
if "safe_radius" not in st.session_state:
    st.session_state["safe_radius"] = 5.0

# 侧边栏
with st.sidebar:
    st.title("导航")
    if st.button("✈️ 航线规划", use_container_width=True):
        st.session_state["page"] = "航线规划"
    if st.button("📡 飞行监控", use_container_width=True):
        st.session_state["page"] = "飞行监控"
    st.info(f"已保存障碍物: {len(st.session_state['obstacles'])} 个")

# ===================== 航线规划页面（含高度、绕行逻辑）=====================
if st.session_state["page"] == "航线规划":
    st.title("✈️ 航线规划（含高度与绕行逻辑）")
    col1, col2 = st.columns([3,1])

    with col1:
        center_gcj = wgs84_to_gcj02(32.233, 118.749)
        m = folium.Map(
            location=center_gcj,
            zoom_start=17,
            tiles="https://webst02.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
            attr="高德地图 © AutoNavi"
        )
        start_gcj = wgs84_to_gcj02(st.session_state["start_point"]["lat"], st.session_state["start_point"]["lon"])
        end_gcj   = wgs84_to_gcj02(st.session_state["end_point"]["lat"], st.session_state["end_point"]["lon"])
        folium.Marker(start_gcj, popup="起点A", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker(end_gcj, popup="终点B", icon=folium.Icon(color="green")).add_to(m)
        folium.PolyLine([start_gcj, end_gcj], color="blue", weight=3, dash_array="5,5").add_to(m)

        # 绘制障碍物（含高度标注）
        for obs in st.session_state["obstacles"]:
            if obs["type"] == "polygon":
                coords = [wgs84_to_gcj02(c[0],c[1]) for c in obs["coordinates"]]
                folium.Polygon(locations=coords, color="red", fill=True, fill_color="red", fill_opacity=0.4,
                               popup=f"障碍物 | 高度: {obs['height']}m").add_to(m)
            elif obs["type"] == "rectangle":
                bounds = [wgs84_to_gcj02(c[0],c[1]) for c in obs["bounds"]]
                folium.Rectangle(bounds=bounds, color="red", fill=True, fill_color="red", fill_opacity=0.4,
                                 popup=f"障碍物 | 高度: {obs['height']}m").add_to(m)
            elif obs["type"] == "circle":
                center = wgs84_to_gcj02(obs["center"][0], obs["center"][1])
                folium.Circle(location=center, radius=obs["radius"],
                              color="red", fill=True, fill_color="red", fill_opacity=0.4,
                              popup=f"障碍物 | 高度: {obs['height']}m").add_to(m)

        draw = folium.plugins.Draw(
            export=True,
            draw_options={"polyline":False, "rectangle":True, "polygon":True, "circle":True, "marker":False}
        )
        draw.add_to(m)

        map_data = st_folium(m, width=800, height=600, returned_objects=["last_active_drawing"])

    with col2:
        st.subheader("📍 航点与无人机参数")
        a_lat = st.number_input("A纬度", value=st.session_state["start_point"]["lat"], format="%.4f")
        a_lon = st.number_input("A经度", value=st.session_state["start_point"]["lon"], format="%.4f")
        if st.button("设置A点"):
            st.session_state["start_point"] = {"lat":a_lat, "lon":a_lon}
            st.success("✅ A点已设置")

        b_lat = st.number_input("B纬度", value=st.session_state["end_point"]["lat"], format="%.4f")
        b_lon = st.number_input("B经度", value=st.session_state["end_point"]["lon"], format="%.4f")
        if st.button("设置B点"):
            st.session_state["end_point"] = {"lat":b_lat, "lon":b_lon}
            st.success("✅ B点已设置")

        st.markdown("---")
        st.subheader("🚁 无人机飞行参数")
        st.session_state["drone_height"] = st.number_input("飞行高度 (m)", min_value=0.0, max_value=1000.0, value=20.0, step=1.0)
        st.session_state["safe_radius"] = st.number_input("安全半径 (m)", min_value=1.0, max_value=20.0, value=5.0, step=1.0)

        st.markdown("---")
        st.subheader("🚧 障碍物操作（含高度）")
        obstacle_height = st.number_input("障碍物高度 (m)", min_value=0.0, max_value=1000.0, value=10.0, step=1.0)
        st.write("1. 地图画图形")
        st.write("2. 设置障碍物高度")
        st.write("3. 点按钮保存")

        if st.button("💾 保存当前障碍物", type="primary"):
            draw_data = map_data.get("last_active_drawing")
            if not draw_data:
                st.warning("⚠️ 先在地图画一个障碍物")
            else:
                geo = draw_data["geometry"]
                typ = geo["type"]
                obs = None
                if typ == "Polygon":
                    coords = [gcj02_to_wgs84(p[1], p[0]) for p in geo["coordinates"][0]]
                    obs = {"type":"polygon", "coordinates":coords, "height": obstacle_height}
                elif typ == "Rectangle":
                    bounds = [gcj02_to_wgs84(p[1], p[0]) for p in geo["coordinates"][0]]
                    obs = {"type":"rectangle", "bounds":bounds, "height": obstacle_height}
                elif typ == "Circle":
                    c = geo["coordinates"]
                    lat, lon = gcj02_to_wgs84(c[1], c[0])
                    r = draw_data["properties"]["radius"]
                    obs = {"type":"circle", "center":[lat, lon], "radius":r, "height": obstacle_height}

                if obs:
                    st.session_state["obstacles"].append(obs)
                    save_obstacles(st.session_state["obstacles"])
                    st.success(f"✅ 保存成功，总数：{len(st.session_state['obstacles'])}")
                    st.rerun()

        if st.button("🗑️ 清除全部障碍物"):
            st.session_state["obstacles"] = []
            save_obstacles([])
            st.warning("⚠️ 已清空所有障碍物")
            st.rerun()

        st.markdown("---")
        st.subheader("🛤️ 航线生成（3种模式）")
        route_mode = st.selectbox("航线模式", ["最佳航线", "向左绕行", "向右绕行"])
        if st.button("生成航线", type="primary"):
            drone_h = st.session_state["drone_height"]
            max_obs_h = max([obs["height"] for obs in st.session_state["obstacles"]], default=0)

            if drone_h > max_obs_h:
                st.success("✅ 飞行高度 > 障碍物高度，可直接飞跃！")
            else:
                st.warning("⚠️ 飞行高度 < 障碍物高度，需绕行！")

            st.info(f"当前选择：{route_mode}")

# ===================== 飞行监控页面（心跳包）=====================
elif st.session_state["page"] == "飞行监控":
    st.title("📡 飞行监控（心跳包）")
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    with col_btn1:
        if st.button("正常运行"):
            st.session_state["status"] = "正常运行"
    with col_btn2:
        if st.button("暂停"):
            st.session_state["status"] = "暂停"
    with col_btn3:
        if st.button("断连报警"):
            st.session_state["status"] = "断连报警"

    status_text = st.empty()
    chart = st.empty()
    table = st.empty()

    if st.session_state["status"] == "正常运行":
        for i in range(100):
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            st.session_state["heartbeat_data"].append({
                "序号":i+1, "时间戳":timestamp, "状态":"在线"
            })
            if len(st.session_state["heartbeat_data"]) > 50:
                st.session_state["heartbeat_data"].pop(0)
            df = pd.DataFrame(st.session_state["heartbeat_data"])
            status_text.metric("连接状态", "在线")
            chart.line_chart(df, x="序号", y="序号")
            table.dataframe(df.tail(10), use_container_width=True)
            time.sleep(0.5)
    elif st.session_state["status"] == "暂停":
        status_text.info("系统已暂停")
    else:
        status_text.error("⚠️ 断连报警！")
