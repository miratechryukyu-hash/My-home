import json

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import trimesh
from streamlit_plotly_events import plotly_events

st.set_page_config(
    page_title="自宅レイアウトイメージ",
    layout="wide",
    initial_sidebar_state="expanded",
)

CANVAS_PADDING = 40
CANVAS_MAX_PX = 680

# 関東間（1畳 182cm×91cm）を基準にした一般的な目安（幅 × 奥行 × 高さ cm）
ROOM_PRESETS = {
    "4.5畳（約 2.7 × 2.7 m）": (273, 273, 240),
    "6畳（約 3.6 × 2.7 m）": (364, 273, 240),
    "7畳（約 3.6 × 3.2 m）": (364, 318, 240),
    "8畳（約 3.6 × 3.6 m）": (364, 364, 240),
    "10畳（約 4.6 × 3.6 m）": (455, 364, 240),
    "12畳（約 5.5 × 4.6 m）": (546, 455, 240),
}
PRESET_OPTIONS = list(ROOM_PRESETS.keys()) + ["自分で入力（cm）"]

LEGACY_PRESET_MAP = {
    "4.5畳（約 273 × 273 cm）": "4.5畳（約 2.7 × 2.7 m）",
    "6畳（約 364 × 273 cm）": "6畳（約 3.6 × 2.7 m）",
    "7畳（約 364 × 318 cm）": "7畳（約 3.6 × 3.2 m）",
    "8畳（約 364 × 364 cm）": "8畳（約 3.6 × 3.6 m）",
    "10畳（約 455 × 364 cm）": "10畳（約 4.6 × 3.6 m）",
    "12畳（約 546 × 455 cm）": "12畳（約 5.5 × 4.6 m）",
}

# ── 家具メッシュ生成（単位: cm） ───────────────────────────────


def cm_to_m(cm):
    return cm / 100.0


def format_m(cm, digits=1):
    return f"{cm_to_m(cm):.{digits}f} m"


def _box(extents, color="lightgray"):
    return trimesh.creation.box(extents=extents)


def create_bunk_bed():
    parts = []
    bed_w, bed_d, bed_h = 100, 200, 35
    gap = 90

    for z in [bed_h / 2, bed_h / 2 + gap]:
        mattress = _box([bed_w, bed_d, bed_h])
        mattress.apply_translation([0, 0, z])
        parts.append(mattress)

        for dx, dy in [
            (-bed_w / 2 + 5, -bed_d / 2 + 5),
            (bed_w / 2 - 5, -bed_d / 2 + 5),
            (-bed_w / 2 + 5, bed_d / 2 - 5),
            (bed_w / 2 - 5, bed_d / 2 - 5),
        ]:
            leg = _box([8, 8, z])
            leg.apply_translation([dx, dy, z / 2])
            parts.append(leg)

    ladder = _box([8, 8, gap + bed_h])
    ladder.apply_translation([bed_w / 2 + 10, 0, (gap + bed_h) / 2])
    parts.append(ladder)

    return trimesh.util.concatenate(parts)


def create_single_bed():
    bed_w, bed_d, bed_h = 100, 200, 35
    mattress = _box([bed_w, bed_d, bed_h])
    mattress.apply_translation([0, 0, bed_h / 2])
    return mattress


def create_desk():
    top = _box([120, 60, 4])
    top.apply_translation([0, 0, 74])
    leg_h = 72
    legs = []
    for x, y in [(-55, -25), (55, -25), (-55, 25), (55, 25)]:
        leg = _box([6, 6, leg_h])
        leg.apply_translation([x, y, leg_h / 2])
        legs.append(leg)
    return trimesh.util.concatenate([top, *legs])


def create_sofa():
    seat = _box([180, 80, 40])
    seat.apply_translation([0, 0, 20])
    back = _box([180, 15, 70])
    back.apply_translation([0, -32.5, 55])
    return trimesh.util.concatenate([seat, back])


def create_chair():
    seat = _box([45, 45, 5])
    seat.apply_translation([0, 0, 47.5])
    back = _box([45, 5, 45])
    back.apply_translation([0, -20, 67.5])
    return trimesh.util.concatenate([seat, back])


def create_generic_box():
    """手入力家具用の汎用ボックス（100×100×100 cm、底面 z=0）"""
    box = _box([100, 100, 100])
    box.apply_translation([0, 0, 50])
    return box


CUSTOM_FURNITURE_COLOR = "#757575"
CUSTOM_FURNITURE_DEFAULT_CM = {"width": 100, "depth": 100, "height": 100}

FURNITURE_CATALOG = {
    "2段ベッド": {
        "factory": create_bunk_bed,
        "color": "#E53935",
        "default_cm": {"width": 100, "depth": 200, "height": 220},
    },
    "シングルベッド": {
        "factory": create_single_bed,
        "color": "#FB8C00",
        "default_cm": {"width": 100, "depth": 200, "height": 50},
    },
    "椅子": {
        "factory": create_chair,
        "color": "#43A047",
        "default_cm": {"width": 45, "depth": 45, "height": 90},
    },
    "デスク": {
        "factory": create_desk,
        "color": "#1E88E5",
        "default_cm": {"width": 120, "depth": 60, "height": 75},
    },
    "ソファ": {
        "factory": create_sofa,
        "color": "#8E24AA",
        "default_cm": {"width": 180, "depth": 80, "height": 85},
    },
}


def is_custom_furniture(item):
    return bool(item.get("is_custom")) or item["name"] not in FURNITURE_CATALOG


def get_furniture_info(item):
    if is_custom_furniture(item):
        return {
            "factory": create_generic_box,
            "color": CUSTOM_FURNITURE_COLOR,
            "default_cm": CUSTOM_FURNITURE_DEFAULT_CM,
        }
    return FURNITURE_CATALOG[item["name"]]


def new_furniture_position(existing_count, room_width_cm, room_depth_cm):
    """新しい家具が重ならないよう、初期位置をずらす"""
    slots = [
        (0, 0),
        (-room_width_cm / 4, 0),
        (room_width_cm / 4, 0),
        (0, room_depth_cm / 4),
        (0, -room_depth_cm / 4),
        (-room_width_cm / 4, room_depth_cm / 4),
        (room_width_cm / 4, -room_depth_cm / 4),
    ]
    x, y = slots[existing_count % len(slots)]
    return [round(x, 1), round(y, 1), 0]


def render_color_legend():
    cols = st.columns(len(FURNITURE_CATALOG))
    for col, (name, info) in zip(cols, FURNITURE_CATALOG.items()):
        col.markdown(
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<span style="width:16px;height:16px;background:{info["color"]};'
            f'border:1px solid #333;display:inline-block;"></span>'
            f"<span>{name}</span></div>",
            unsafe_allow_html=True,
        )


def normalize_furniture_item(item):
    catalog = get_furniture_info(item)
    defaults = catalog["default_cm"]
    scale = float(item.get("scale", 1.0) or 1.0)
    return {
        "name": item["name"],
        "position": item["position"],
        "rotation": float(item.get("rotation", 0) or 0),
        "width_cm": float(item.get("width_cm", defaults["width"] * scale)),
        "depth_cm": float(item.get("depth_cm", defaults["depth"] * scale)),
        "height_cm": float(item.get("height_cm", defaults["height"] * scale)),
        "is_custom": is_custom_furniture(item),
    }


def furniture_scale_xyz(name, width_cm, depth_cm, height_cm, is_custom=False):
    if is_custom or name not in FURNITURE_CATALOG:
        defaults = CUSTOM_FURNITURE_DEFAULT_CM
    else:
        defaults = FURNITURE_CATALOG[name]["default_cm"]
    return (
        width_cm / defaults["width"],
        depth_cm / defaults["depth"],
        height_cm / defaults["height"],
    )


def create_room(width_cm, depth_cm, height_cm):
    floor = _box([width_cm, depth_cm, 2])
    floor.apply_translation([0, 0, 1])
    parts = [floor]

    wall_specs = [
        ([2, depth_cm, height_cm], [-width_cm / 2 + 1, 0, height_cm / 2]),
        ([2, depth_cm, height_cm], [width_cm / 2 - 1, 0, height_cm / 2]),
        ([width_cm, 2, height_cm], [0, -depth_cm / 2 + 1, height_cm / 2]),
        ([width_cm, 2, height_cm], [0, depth_cm / 2 - 1, height_cm / 2]),
    ]
    for extents, pos in wall_specs:
        wall = _box(extents)
        wall.apply_translation(pos)
        parts.append(wall)

    return trimesh.util.concatenate(parts)


def apply_transform(mesh, position_cm, rotation_deg, scale_xyz=(1.0, 1.0, 1.0)):
    m = mesh.copy()
    sx, sy, sz = scale_xyz
    if sx != 1.0 or sy != 1.0 or sz != 1.0:
        m.apply_scale([sx, sy, sz])
    if rotation_deg:
        rot = trimesh.transformations.rotation_matrix(
            np.radians(rotation_deg), [0, 0, 1]
        )
        m.apply_transform(rot)
    min_z = m.bounds[0][2]
    if min_z != 0:
        m.apply_translation([0, 0, -min_z])
    m.apply_translation(position_cm)
    return m


def mesh_to_trace(mesh, color, name, opacity=0.85):
    return go.Mesh3d(
        x=mesh.vertices[:, 0],
        y=mesh.vertices[:, 1],
        z=mesh.vertices[:, 2],
        i=mesh.faces[:, 0],
        j=mesh.faces[:, 1],
        k=mesh.faces[:, 2],
        color=color,
        opacity=opacity,
        name=name,
        hoverinfo="name",
    )


def build_scene_figure(room_mesh, placed_items):
    traces = [mesh_to_trace(room_mesh, "#E8E4DF", "部屋", opacity=0.35)]
    for item in placed_items:
        traces.append(
            mesh_to_trace(item["mesh"], item["color"], item["name"], opacity=0.9)
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="家具配置シミュレーション（3D）",
        scene=dict(
            aspectmode="data",
            xaxis_title="幅 (cm)",
            yaxis_title="奥行 (cm)",
            zaxis_title="高さ (cm)",
            camera=dict(eye=dict(x=1.6, y=-1.8, z=1.2)),
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def build_placed_items(placed_furniture):
    placed_items = []
    for raw in placed_furniture:
        cfg = normalize_furniture_item(raw)
        catalog = get_furniture_info(raw)
        scale_xyz = furniture_scale_xyz(
            cfg["name"],
            cfg["width_cm"],
            cfg["depth_cm"],
            cfg["height_cm"],
            cfg["is_custom"],
        )
        position_3d = [cfg["position"][0], cfg["position"][1], 0]
        mesh = apply_transform(
            catalog["factory"](),
            position_3d,
            cfg["rotation"],
            scale_xyz,
        )
        placed_items.append(
            {"mesh": mesh, "color": catalog["color"], "name": cfg["name"]}
        )
    return placed_items


def furniture_half_extents(width_cm, depth_cm, rotation_deg):
    angle = np.radians(rotation_deg % 360)
    cos_a, sin_a = abs(np.cos(angle)), abs(np.sin(angle))
    half_x = (width_cm * cos_a + depth_cm * sin_a) / 2
    half_y = (width_cm * sin_a + depth_cm * cos_a) / 2
    return half_x, half_y


def clamp_furniture_position(
    x_cm, y_cm, width_cm, depth_cm, room_width_cm, room_depth_cm, rotation_deg=0
):
    half_x, half_y = furniture_half_extents(width_cm, depth_cm, rotation_deg)
    x = max(-room_width_cm / 2 + half_x, min(room_width_cm / 2 - half_x, x_cm))
    y = max(-room_depth_cm / 2 + half_y, min(room_depth_cm / 2 - half_y, y_cm))
    return round(x, 1), round(y, 1)


def rotated_rect_corners(x_cm, y_cm, width_cm, depth_cm, rotation_deg):
    angle = np.radians(rotation_deg)
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    local_corners = [
        (-width_cm / 2, -depth_cm / 2),
        (width_cm / 2, -depth_cm / 2),
        (width_cm / 2, depth_cm / 2),
        (-width_cm / 2, depth_cm / 2),
    ]
    corners = []
    for lx, ly in local_corners:
        rx = lx * cos_a - ly * sin_a + x_cm
        ry = lx * sin_a + ly * cos_a + y_cm
        corners.append((rx, ry))
    return corners


def apply_pending_move_index():
    pending = st.session_state.pop("pending_move_index", None)
    if pending is not None:
        st.session_state["active_furniture_index"] = pending


def get_selected_furniture_index():
    idx = int(st.session_state.get("active_furniture_index", 0))
    max_idx = max(0, len(st.session_state.placed_furniture) - 1)
    return min(idx, max_idx)


def furniture_option_label(index):
    item = normalize_furniture_item(st.session_state.placed_furniture[index])
    return (
        f"{index + 1}. {item['name']} "
        f"（{format_m(item['width_cm'])}×{format_m(item['depth_cm'])}）"
    )


def render_selected_furniture_summary(index):
    raw = st.session_state.placed_furniture[index]
    item = normalize_furniture_item(raw)
    color = get_furniture_info(raw)["color"]
    st.markdown(
        f"""
        **選択中の家具:** {item['name']}  
        **サイズ:** {item['width_cm']:.0f} × {item['depth_cm']:.0f} × {item['height_cm']:.0f} cm  
        **位置:** 横 {format_m(item['position'][0])} / 奥行 {format_m(item['position'][1])}  
        **向き:** {item['rotation']:.0f} 度
        """
    )
    st.markdown(
        f'<span style="display:inline-block;width:18px;height:18px;'
        f'background:{color};border:1px solid #333;margin-right:6px;"></span>'
        f'<span>色: {item["name"]}</span>',
        unsafe_allow_html=True,
    )


def build_floor_plan_figure(placed_furniture, room_width_cm, room_depth_cm):
    rw_m = cm_to_m(room_width_cm)
    rd_m = cm_to_m(room_depth_cm)
    margin_m = 0.4
    fig = go.Figure()

    fig.add_shape(
        type="rect",
        x0=-rw_m / 2,
        y0=-rd_m / 2,
        x1=rw_m / 2,
        y1=rd_m / 2,
        line=dict(color="#666666", width=2),
        fillcolor="#F3F0EB",
        layer="below",
    )

    for raw in placed_furniture:
        item = normalize_furniture_item(raw)
        catalog = get_furniture_info(raw)
        x_m = cm_to_m(item["position"][0])
        y_m = cm_to_m(item["position"][1])
        w_m = cm_to_m(item["width_cm"])
        d_m = cm_to_m(item["depth_cm"])
        rotation = item["rotation"]
        corners = rotated_rect_corners(
            item["position"][0],
            item["position"][1],
            item["width_cm"],
            item["depth_cm"],
            rotation,
        )
        xs = [cm_to_m(c[0]) for c in corners] + [cm_to_m(corners[0][0])]
        ys = [cm_to_m(c[1]) for c in corners] + [cm_to_m(corners[0][1])]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                fill="toself",
                fillcolor=catalog["color"],
                line=dict(color="#222222", width=2),
                opacity=0.88,
                mode="lines",
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=x_m,
            y=y_m,
            text=(
                f"{item['name']}<br>{w_m:.1f}×{d_m:.1f} m"
                f"<br>{rotation:.0f}°"
            ),
            showarrow=False,
            font=dict(size=11, color="#111111"),
        )

    fig.update_layout(
        title="間取り図",
        xaxis=dict(
            title="幅 (m)",
            range=[-rw_m / 2 - margin_m, rw_m / 2 + margin_m],
            tickformat=".1f",
            constrain="domain",
        ),
        yaxis=dict(
            title="奥行 (m)",
            range=[-rd_m / 2 - margin_m, rd_m / 2 + margin_m],
            tickformat=".1f",
            scaleanchor="x",
            scaleratio=1,
        ),
        height=max(420, min(560, int(420 * rd_m / max(rw_m, 0.01)))),
        margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor="#FFFFFF",
        dragmode=False,
    )
    return fig


def move_selected_furniture(dx_cm, dy_cm, room_width_cm, room_depth_cm):
    idx = get_selected_furniture_index()
    item = normalize_furniture_item(st.session_state.placed_furniture[idx])
    x, y = clamp_furniture_position(
        item["position"][0] + dx_cm,
        item["position"][1] + dy_cm,
        item["width_cm"],
        item["depth_cm"],
        room_width_cm,
        room_depth_cm,
        item["rotation"],
    )
    st.session_state.placed_furniture[idx]["position"] = [x, y, 0]


def snap_selected_furniture_to_wall(wall, room_width_cm, room_depth_cm):
    idx = get_selected_furniture_index()
    item = normalize_furniture_item(st.session_state.placed_furniture[idx])
    half_x, half_y = furniture_half_extents(
        item["width_cm"], item["depth_cm"], item["rotation"]
    )
    x, y = item["position"][0], item["position"][1]

    if wall == "back":
        y = room_depth_cm / 2 - half_y
    elif wall == "front":
        y = -room_depth_cm / 2 + half_y
    elif wall == "left":
        x = -room_width_cm / 2 + half_x
    elif wall == "right":
        x = room_width_cm / 2 - half_x

    x, y = clamp_furniture_position(
        x,
        y,
        item["width_cm"],
        item["depth_cm"],
        room_width_cm,
        room_depth_cm,
        item["rotation"],
    )
    st.session_state.placed_furniture[idx]["position"] = [x, y, 0]


def canvas_scale(room_width_cm, room_depth_cm):
    px_per_cm = (CANVAS_MAX_PX - 2 * CANVAS_PADDING) / max(room_width_cm, room_depth_cm)
    canvas_w = int(room_width_cm * px_per_cm + 2 * CANVAS_PADDING)
    canvas_h = int(room_depth_cm * px_per_cm + 2 * CANVAS_PADDING)
    return px_per_cm, canvas_w, canvas_h


def room_cm_to_canvas(position_cm, room_width_cm, room_depth_cm, px_per_cm):
    x_px = CANVAS_PADDING + (position_cm[0] + room_width_cm / 2) * px_per_cm
    y_px = CANVAS_PADDING + (room_depth_cm / 2 - position_cm[1]) * px_per_cm
    return x_px, y_px


def canvas_to_room_cm(x_px, y_px, room_width_cm, room_depth_cm, px_per_cm):
    x_cm = (x_px - CANVAS_PADDING) / px_per_cm - room_width_cm / 2
    y_cm = room_depth_cm / 2 - (y_px - CANVAS_PADDING) / px_per_cm
    return x_cm, y_cm


def build_canvas_drawing(placed_furniture, room_width_cm, room_depth_cm):
    px_per_cm, _, _ = canvas_scale(room_width_cm, room_depth_cm)
    objects = [
        {
            "type": "rect",
            "left": CANVAS_PADDING,
            "top": CANVAS_PADDING,
            "width": room_width_cm * px_per_cm,
            "height": room_depth_cm * px_per_cm,
            "fill": "#F3F0EB",
            "stroke": "#666666",
            "strokeWidth": 2,
            "selectable": False,
            "evented": False,
            "name": "__room__",
        }
    ]

    for index, raw in enumerate(placed_furniture):
        item = normalize_furniture_item(raw)
        catalog = get_furniture_info(raw)
        defaults = catalog["default_cm"]
        scale_x = item["width_cm"] / defaults["width"]
        scale_y = item["depth_cm"] / defaults["depth"]
        base_w_px = defaults["width"] * px_per_cm
        base_h_px = defaults["depth"] * px_per_cm
        cx, cy = room_cm_to_canvas(
            item["position"], room_width_cm, room_depth_cm, px_per_cm
        )
        draw_w = base_w_px * scale_x
        draw_h = base_h_px * scale_y
        objects.append(
            {
                "type": "rect",
                "left": cx - draw_w / 2,
                "top": cy - draw_h / 2,
                "width": base_w_px,
                "height": base_h_px,
                "scaleX": scale_x,
                "scaleY": scale_y,
                "angle": item["rotation"],
                "fill": catalog["color"],
                "opacity": 0.92,
                "stroke": "#222222",
                "strokeWidth": 2,
                "name": f"{item['name']}::{index}",
            }
        )
        label = f"{item['name']}\n{item['width_cm']:.0f}×{item['depth_cm']:.0f}cm"
        objects.append(
            {
                "type": "textbox",
                "left": cx - 40,
                "top": cy - 10,
                "width": 80,
                "height": 20,
                "text": label,
                "fontSize": 14,
                "fill": "#222222",
                "backgroundColor": "rgba(255,255,255,0.75)",
                "editable": False,
                "selectable": False,
                "evented": False,
                "angle": item["rotation"],
                "originX": "center",
                "originY": "center",
                "name": f"__label__::{index}",
            }
        )

    return {"version": "4.4.0", "objects": objects}


def parse_canvas_furniture(canvas_json, room_width_cm, room_depth_cm, current_items=None):
    if not canvas_json:
        return None

    px_per_cm, _, _ = canvas_scale(room_width_cm, room_depth_cm)
    parsed = []

    for obj in canvas_json.get("objects", []):
        if obj.get("type") != "rect":
            continue

        name = obj.get("name")
        if not name or name.startswith("__") or "::" not in name:
            continue

        try:
            name_part, index_part = name.rsplit("::", 1)
            index = int(index_part)
            scale_x = float(obj.get("scaleX", 1) or 1)
            scale_y = float(obj.get("scaleY", 1) or 1)
            width_px = float(obj["width"]) * scale_x
            height_px = float(obj["height"]) * scale_y
            cx = float(obj["left"]) + width_px / 2
            cy = float(obj["top"]) + height_px / 2
        except (KeyError, TypeError, ValueError):
            continue

        x_cm, y_cm = canvas_to_room_cm(cx, cy, room_width_cm, room_depth_cm, px_per_cm)
        width_cm = round(width_px / px_per_cm, 1)
        depth_cm = round(height_px / px_per_cm, 1)

        if current_items and index < len(current_items):
            height_cm = normalize_furniture_item(current_items[index])["height_cm"]
        else:
            height_cm = FURNITURE_CATALOG[name_part]["default_cm"]["height"]

        parsed.append(
            {
                "index": index,
                "name": name_part,
                "position": [round(x_cm, 1), round(y_cm, 1), 0],
                "rotation": round(float(obj.get("angle", 0) or 0), 1),
                "width_cm": width_cm,
                "depth_cm": depth_cm,
                "height_cm": height_cm,
            }
        )

    parsed.sort(key=lambda item: item["index"])
    return [
        {
            "name": item["name"],
            "position": item["position"],
            "rotation": item["rotation"],
            "width_cm": item["width_cm"],
            "depth_cm": item["depth_cm"],
            "height_cm": item["height_cm"],
        }
        for item in parsed
    ]


def init_session_state():
    if "room_photos" not in st.session_state:
        st.session_state.room_photos = []
    if "placed_furniture" not in st.session_state:
        st.session_state.placed_furniture = []
    if "room_size" not in st.session_state:
        st.session_state.room_size = ROOM_PRESETS["6畳（約 3.6 × 2.7 m）"]
    elif st.session_state.room_size[0] < 50:
        st.session_state.room_size = tuple(v * 100 for v in st.session_state.room_size)
    if "room_preset" not in st.session_state:
        st.session_state.room_preset = "6畳（約 3.6 × 2.7 m）"
    elif st.session_state.room_preset in LEGACY_PRESET_MAP:
        st.session_state.room_preset = LEGACY_PRESET_MAP[st.session_state.room_preset]


def migrate_placed_furniture():
    st.session_state.placed_furniture = [
        normalize_furniture_item(item) for item in st.session_state.placed_furniture
    ]


init_session_state()
migrate_placed_furniture()

# ── UI ────────────────────────────────────────────────────────

st.title("自宅レイアウトイメージ共有")
st.markdown(
    """
**このアプリでできること（現在）**

1. 畳数（6畳・7畳など）を選んで、部屋の3D空間を作る
2. 間取り図（m表示）で家具を配置し、レイアウトイメージを作る
3. 3Dシミュレーションを画像として保存・共有する

**写真について（重要）**

写真からAIが部屋を自動認識する機能は **まだ実装されていません**。
今は **畳数・サイズ入力** で部屋を作っています。
写真機能は、将来そのAI読み取りに使うための準備段階です。
"""
)

tab_room, tab_layout, tab_share = st.tabs(
    ["1. 部屋の設定", "2. 家具の配置", "3. プレビューと共有"]
)

# ── Tab 1: 部屋の設定 ─────────────────────────────────────────

with tab_room:
    st.subheader("部屋のサイズ")
    st.caption("畳数を選ぶと、一般的なお部屋の大きさが自動で入ります。")

    preset_index = (
        PRESET_OPTIONS.index(st.session_state.room_preset)
        if st.session_state.room_preset in PRESET_OPTIONS
        else 1
    )
    selected_preset = st.selectbox(
        "部屋の広さ",
        PRESET_OPTIONS,
        index=preset_index,
        help="目安のサイズです。実際の部屋と違う場合は「自分で入力（cm）」を選んでください。",
    )

    if selected_preset != st.session_state.room_preset:
        st.session_state.room_preset = selected_preset

    if selected_preset != "自分で入力（cm）":
        new_size = ROOM_PRESETS[selected_preset]
        st.session_state.room_size = new_size
        rw, rd, rh = st.session_state.room_size
        st.info(
            f"設定中: 幅 {format_m(rw)} × 奥行 {format_m(rd)} × 高さ {format_m(rh)}"
        )
    else:
        c1, c2, c3 = st.columns(3)
        room_width = c1.number_input(
            "幅 (cm)",
            min_value=200,
            max_value=1500,
            value=int(st.session_state.room_size[0]),
            step=10,
        )
        room_depth = c2.number_input(
            "奥行 (cm)",
            min_value=200,
            max_value=1500,
            value=int(st.session_state.room_size[1]),
            step=10,
        )
        room_height = c3.number_input(
            "高さ (cm)",
            min_value=200,
            max_value=400,
            value=int(st.session_state.room_size[2]),
            step=5,
        )
        new_size = (room_width, room_depth, room_height)
        st.session_state.room_size = new_size

    st.divider()
    st.subheader("写真から部屋を読み取る（開発予定）")
    st.markdown(
        """
        **目指している機能**

        1. 部屋の写真を撮る
        2. AIが空間の形や、すでに置いてある物を読み取る
        3. おおよそのバーチャル空間を自動生成する

        **現在**

        - 上記のAI読み取りは **未実装** です
        - 今の3D空間は **畳数・サイズ入力** から作っています
        - 写真を撮っても、配置シミュレーションには **まだ反映されません**
        """
    )

    with st.expander("将来のAI用：部屋の写真を保存（任意・現在未使用）"):
        st.caption(
            "開発が進んだら、この写真から部屋を自動認識する予定です。"
            "今は保存のみで、シミュレーションには使われません。"
        )

        col_cam, col_upload = st.columns(2)

        with col_cam:
            st.markdown("**カメラで撮影**")
            camera_photo = st.camera_input("部屋の写真", label_visibility="collapsed")

        with col_upload:
            st.markdown("**ファイルからアップロード**")
            uploaded_photos = st.file_uploader(
                "写真（複数可）",
                type=["jpg", "jpeg", "png", "heic"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )

        pending = []
        if camera_photo is not None:
            pending.append(("カメラ撮影", camera_photo.getvalue()))
        if uploaded_photos:
            for photo in uploaded_photos:
                pending.append((photo.name, photo.getvalue()))

        bc1, bc2 = st.columns(2)
        if bc1.button("写真を保存", type="primary", disabled=not pending):
            st.session_state.room_photos = [
                {"label": label, "data": data} for label, data in pending
            ]
            st.rerun()

        if bc2.button("保存した写真を削除", disabled=not st.session_state.room_photos):
            st.session_state.room_photos = []
            st.rerun()

        if st.session_state.room_photos:
            st.success(f"{len(st.session_state.room_photos)} 枚を保存中（AI解析待ち）")
            cols = st.columns(min(len(st.session_state.room_photos), 4))
            for i, photo in enumerate(st.session_state.room_photos):
                cols[i % len(cols)].image(
                    photo["data"], caption=photo["label"], use_container_width=True
                )

# ── Tab 2: 家具の配置 ─────────────────────────────────────────

with tab_layout:
    st.subheader("間取り図で家具を配置")
    render_color_legend()
    rw, rd, rh = st.session_state.room_size

    # ── 1. 家具を選ぶ ───────────────────────────────────────────
    st.markdown("### 1. 家具を選ぶ")
    add_mode = st.radio(
        "追加方法",
        ["カタログから選ぶ", "名前とサイズを手入力"],
        horizontal=True,
        key="furniture_add_mode",
    )

    if add_mode == "カタログから選ぶ":
        st.caption("カタログから種類を選び、サイズを調整して追加できます。")
        furniture_name = st.selectbox(
            "追加する家具の種類",
            list(FURNITURE_CATALOG.keys()),
            key="furniture_select",
        )
        add_display_name = furniture_name
        add_is_custom = False
        defaults = FURNITURE_CATALOG[furniture_name]["default_cm"]
        add_color = FURNITURE_CATALOG[furniture_name]["color"]
        size_key_suffix = furniture_name
    else:
        st.caption("家具名とサイズ（横・奥行・高さ）を自由に入力して追加できます。")
        add_display_name = st.text_input(
            "家具名",
            placeholder="例: 本棚、タンス、テレビ台",
            key="custom_furniture_name",
        )
        add_is_custom = True
        defaults = CUSTOM_FURNITURE_DEFAULT_CM
        add_color = CUSTOM_FURNITURE_COLOR
        size_key_suffix = "custom"

    st.markdown(
        f'<span style="display:inline-block;width:14px;height:14px;background:{add_color};'
        f'border:1px solid #333;margin-right:6px;"></span>'
        f"**追加する家具:** {add_display_name or '（名前未入力）'}",
        unsafe_allow_html=True,
    )

    size_c1, size_c2, size_c3 = st.columns(3)
    add_width_cm = size_c1.number_input(
        "横（幅）cm",
        min_value=30,
        max_value=400,
        value=int(defaults["width"]),
        step=5,
        key=f"add_furniture_width_{size_key_suffix}",
    )
    add_depth_cm = size_c2.number_input(
        "縦（奥行）cm",
        min_value=30,
        max_value=400,
        value=int(defaults["depth"]),
        step=5,
        key=f"add_furniture_depth_{size_key_suffix}",
    )
    add_height_cm = size_c3.number_input(
        "高さ cm",
        min_value=30,
        max_value=300,
        value=int(defaults["height"]),
        step=5,
        key=f"add_furniture_height_{size_key_suffix}",
    )

    bc1, bc2, bc3 = st.columns(3)
    if bc1.button("この家具を追加", type="primary", use_container_width=True):
        name = add_display_name.strip() if add_is_custom else furniture_name
        if add_is_custom and not name:
            st.error("家具名を入力してください。")
        else:
            count = len(st.session_state.placed_furniture)
            new_item = {
                "name": name,
                "position": new_furniture_position(count, rw, rd),
                "rotation": 0,
                "width_cm": float(add_width_cm),
                "depth_cm": float(add_depth_cm),
                "height_cm": float(add_height_cm),
            }
            if add_is_custom:
                new_item["is_custom"] = True
            st.session_state.placed_furniture.append(new_item)
            st.session_state.pending_move_index = count
            st.rerun()

    if bc2.button("最後の家具を削除", use_container_width=True):
        if st.session_state.placed_furniture:
            st.session_state.placed_furniture.pop()
            st.session_state.pending_move_index = max(
                0, len(st.session_state.placed_furniture) - 1
            )
            st.rerun()

    if bc3.button("すべてクリア", use_container_width=True):
        st.session_state.placed_furniture = []
        st.session_state.pending_move_index = 0
        st.rerun()

    st.divider()

    # ── 2. 配置する家具を選ぶ（手動選択） ───────────────────────
    st.markdown("### 2. 配置する家具を選ぶ")
    if st.session_state.placed_furniture:
        apply_pending_move_index()

        st.caption("操作したい家具を手動で選んでください（移動・回転・サイズ変更の対象）。")
        st.radio(
            "操作する家具（手動選択）",
            options=list(range(len(st.session_state.placed_furniture))),
            format_func=furniture_option_label,
            key="active_furniture_index",
        )

        active_idx = get_selected_furniture_index()
        render_selected_furniture_summary(active_idx)

        with st.expander("配置済み家具一覧"):
            for i, raw in enumerate(st.session_state.placed_furniture, 1):
                item = normalize_furniture_item(raw)
                marker = " ← 選択中" if i - 1 == active_idx else ""
                st.text(
                    f"{i}. {item['name']} — "
                    f"{item['width_cm']:.0f}×{item['depth_cm']:.0f}×{item['height_cm']:.0f} cm, "
                    f"位置 ({format_m(item['position'][0])}, {format_m(item['position'][1])})"
                    f"{marker}"
                )
    else:
        st.info("「1. 家具を選ぶ」で家具を追加すると、ここで操作対象を選べます。")

    st.divider()

    # ── 3. 2D間取り図 ─────────────────────────────────────────
    st.markdown("### 3. 2D間取り図")
    if st.session_state.placed_furniture:
        st.caption("図をタップすると、手順2で選んだ家具がその位置に移動します。")
    else:
        st.caption("家具を追加すると、ここに配置図が表示されます。")

    fig_2d = build_floor_plan_figure(st.session_state.placed_furniture, rw, rd)
    if st.session_state.placed_furniture:
        clicked = plotly_events(
            fig_2d,
            click_event=True,
            hover_event=False,
            select_event=False,
            override_height=450,
            key="floor_plan_click",
        )

        if clicked:
            point = clicked[0]
            idx = get_selected_furniture_index()
            item = normalize_furniture_item(st.session_state.placed_furniture[idx])
            x, y = clamp_furniture_position(
                point["x"] * 100,
                point["y"] * 100,
                item["width_cm"],
                item["depth_cm"],
                rw,
                rd,
                item["rotation"],
            )
            st.session_state.placed_furniture[idx]["position"] = [x, y, 0]
            st.rerun()
    else:
        st.plotly_chart(fig_2d, use_container_width=True, key="floor_plan_empty")

    st.divider()

    # ── 4. 配置操作 ───────────────────────────────────────────
    st.markdown("### 4. 配置操作")
    if st.session_state.placed_furniture:
        active_idx = get_selected_furniture_index()
        edit_item = normalize_furniture_item(st.session_state.placed_furniture[active_idx])

        st.markdown("**位置を微調整（10cm）**")
        n1, n2, n3, n4, n5 = st.columns(5)
        if n2.button("↑ 奥へ", use_container_width=True):
            move_selected_furniture(0, 10, rw, rd)
            st.rerun()
        if n1.button("← 左へ", use_container_width=True):
            move_selected_furniture(-10, 0, rw, rd)
            st.rerun()
        if n3.button("↓ 手前へ", use_container_width=True):
            move_selected_furniture(0, -10, rw, rd)
            st.rerun()
        if n4.button("→ 右へ", use_container_width=True):
            move_selected_furniture(10, 0, rw, rd)
            st.rerun()
        if n5.button("90°回転", use_container_width=True):
            new_rotation = (edit_item["rotation"] + 90) % 360
            x, y = clamp_furniture_position(
                edit_item["position"][0],
                edit_item["position"][1],
                edit_item["width_cm"],
                edit_item["depth_cm"],
                rw,
                rd,
                new_rotation,
            )
            st.session_state.placed_furniture[active_idx] = {
                **edit_item,
                "rotation": new_rotation,
                "position": [x, y, 0],
            }
            st.rerun()

        st.markdown("**壁ぎりぎりに配置**")
        s1, s2, s3, s4 = st.columns(4)
        if s1.button("奥ぎりぎり", use_container_width=True):
            snap_selected_furniture_to_wall("back", rw, rd)
            st.rerun()
        if s2.button("手前ぎりぎり", use_container_width=True):
            snap_selected_furniture_to_wall("front", rw, rd)
            st.rerun()
        if s3.button("左ぎりぎり", use_container_width=True):
            snap_selected_furniture_to_wall("left", rw, rd)
            st.rerun()
        if s4.button("右ぎりぎり", use_container_width=True):
            snap_selected_furniture_to_wall("right", rw, rd)
            st.rerun()

        st.markdown("**サイズを変更（手動入力）**")
        edit_c1, edit_c2, edit_c3 = st.columns(3)
        edit_width = edit_c1.number_input(
            "横（幅）cm",
            min_value=30,
            max_value=400,
            value=int(edit_item["width_cm"]),
            step=5,
            key=f"edit_width_{active_idx}",
        )
        edit_depth = edit_c2.number_input(
            "縦（奥行）cm",
            min_value=30,
            max_value=400,
            value=int(edit_item["depth_cm"]),
            step=5,
            key=f"edit_depth_{active_idx}",
        )
        edit_height = edit_c3.number_input(
            "高さ cm",
            min_value=30,
            max_value=300,
            value=int(edit_item["height_cm"]),
            step=5,
            key=f"edit_height_{active_idx}",
        )
        if st.button("サイズを反映", key="apply_furniture_size"):
            st.session_state.placed_furniture[active_idx] = {
                **edit_item,
                "width_cm": float(edit_width),
                "depth_cm": float(edit_depth),
                "height_cm": float(edit_height),
            }
            st.rerun()
    else:
        st.info("家具を追加すると、配置操作が使えるようになります。")

    st.divider()
    st.subheader("3Dプレビュー")
    room_mesh = create_room(rw, rd, rh)
    fig_layout = build_scene_figure(room_mesh, build_placed_items(st.session_state.placed_furniture))
    st.plotly_chart(fig_layout, use_container_width=True, key="layout_3d_preview")

# ── Tab 3: プレビューと共有 ───────────────────────────────────

with tab_share:
    st.subheader("プレビューと共有")

    rw, rd, rh = st.session_state.room_size
    room_mesh = create_room(rw, rd, rh)
    fig = build_scene_figure(room_mesh, build_placed_items(st.session_state.placed_furniture))

    st.markdown("**家具配置シミュレーション（3D）**")
    st.plotly_chart(fig, use_container_width=True, key="share_3d_preview")

    if st.session_state.room_photos:
        with st.expander(f"保存済みの部屋写真（{len(st.session_state.room_photos)}枚・AI解析待ち）"):
            for photo in st.session_state.room_photos:
                st.image(photo["data"], caption=photo["label"], use_container_width=True)
            st.caption("これらの写真は、将来AIが部屋を読み取る機能で使用する予定です。")

    st.divider()
    st.subheader("イメージを共有")
    st.markdown(
        "3Dシミュレーションを画像として保存し、LINE・メールなどで共有できます。"
    )

    try:
        img_bytes = fig.to_image(format="png", width=1200, height=800, scale=2)
        st.download_button(
            label="レイアウト画像をダウンロード（PNG）",
            data=img_bytes,
            file_name="home_layout.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
    except Exception:
        st.warning(
            "画像の書き出しには kaleido が必要です。"
            "それまでは画面上の3Dビューをスクリーンショットで共有できます。"
        )

    with st.expander("今後追加予定の機能"):
        st.markdown(
            """
            - **写真・動画からAIが部屋を読み取り、3D空間を自動生成**
            - 既存の家具や壁・窓の認識
            - より多くの家具カタログ（カスタムモデルの読み込み）
            - 共有リンクの生成
            """
        )
