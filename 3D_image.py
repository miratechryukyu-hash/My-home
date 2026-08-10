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
    "4.5畳（約 273 × 273 cm）": (273, 273, 240),
    "6畳（約 364 × 273 cm）": (364, 273, 240),
    "7畳（約 364 × 318 cm）": (364, 318, 240),
    "8畳（約 364 × 364 cm）": (364, 364, 240),
    "10畳（約 455 × 364 cm）": (455, 364, 240),
    "12畳（約 546 × 455 cm）": (546, 455, 240),
}
PRESET_OPTIONS = list(ROOM_PRESETS.keys()) + ["自分で入力（cm）"]

# ── 家具メッシュ生成（単位: cm） ───────────────────────────────


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
    catalog = FURNITURE_CATALOG[item["name"]]
    defaults = catalog["default_cm"]
    scale = float(item.get("scale", 1.0) or 1.0)
    return {
        "name": item["name"],
        "position": item["position"],
        "rotation": float(item.get("rotation", 0) or 0),
        "width_cm": float(item.get("width_cm", defaults["width"] * scale)),
        "depth_cm": float(item.get("depth_cm", defaults["depth"] * scale)),
        "height_cm": float(item.get("height_cm", defaults["height"] * scale)),
    }


def furniture_scale_xyz(name, width_cm, depth_cm, height_cm):
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
        catalog = FURNITURE_CATALOG[cfg["name"]]
        scale_xyz = furniture_scale_xyz(
            cfg["name"], cfg["width_cm"], cfg["depth_cm"], cfg["height_cm"]
        )
        position_3d = [
            cfg["position"][0],
            cfg["position"][1],
            cfg["height_cm"] / 2,
        ]
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


def clamp_furniture_position(x_cm, y_cm, width_cm, depth_cm, room_width_cm, room_depth_cm):
    x = max(-room_width_cm / 2 + width_cm / 2, min(room_width_cm / 2 - width_cm / 2, x_cm))
    y = max(-room_depth_cm / 2 + depth_cm / 2, min(room_depth_cm / 2 - depth_cm / 2, y_cm))
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
        st.session_state["move_furniture_select"] = pending


def get_selected_furniture_index():
    idx = int(st.session_state.get("move_furniture_select", 0))
    max_idx = max(0, len(st.session_state.placed_furniture) - 1)
    return min(idx, max_idx)


def build_floor_plan_figure(placed_furniture, room_width_cm, room_depth_cm):
    rw, rd = room_width_cm, room_depth_cm
    fig = go.Figure()

    fig.add_shape(
        type="rect",
        x0=-rw / 2,
        y0=-rd / 2,
        x1=rw / 2,
        y1=rd / 2,
        line=dict(color="#666666", width=2),
        fillcolor="#F3F0EB",
        layer="below",
    )

    for raw in placed_furniture:
        item = normalize_furniture_item(raw)
        catalog = FURNITURE_CATALOG[item["name"]]
        x, y = item["position"][0], item["position"][1]
        w, d = item["width_cm"], item["depth_cm"]
        rotation = item["rotation"]
        corners = rotated_rect_corners(x, y, w, d, rotation)
        xs = [c[0] for c in corners] + [corners[0][0]]
        ys = [c[1] for c in corners] + [corners[0][1]]
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
            x=x,
            y=y,
            text=f"{item['name']}<br>{w:.0f}×{d:.0f}cm<br>{rotation:.0f}°",
            showarrow=False,
            font=dict(size=11, color="#111111"),
        )

    fig.update_layout(
        title="間取り図",
        xaxis=dict(
            title="幅 (cm)",
            range=[-rw / 2 - 40, rw / 2 + 40],
            constrain="domain",
        ),
        yaxis=dict(
            title="奥行 (cm)",
            range=[-rd / 2 - 40, rd / 2 + 40],
            scaleanchor="x",
            scaleratio=1,
        ),
        height=max(420, min(560, int(420 * rd / max(rw, 1)))),
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
        catalog = FURNITURE_CATALOG[item["name"]]
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
        st.session_state.room_size = ROOM_PRESETS["6畳（約 364 × 273 cm）"]
    elif st.session_state.room_size[0] < 50:
        st.session_state.room_size = tuple(v * 100 for v in st.session_state.room_size)
    if "room_preset" not in st.session_state:
        st.session_state.room_preset = "6畳（約 364 × 273 cm）"


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

1. 畳数（6畳・7畳など）を選ぶか、部屋の大きさを入力して3D空間を作る
2. 間取り図上で家具をタッチして動かし、配置イメージを作る
3. 「実際の部屋の写真」と「家具配置の3Dイメージ」を並べて共有する

**写真について**

写真は **「今の部屋の様子」** として共有画面に表示されます。
3D空間は **部屋のサイズ入力** から作っています。
"""
)

tab_room, tab_layout, tab_share = st.tabs(
    ["1. 部屋の設定", "2. 家具の配置", "3. プレビューと共有"]
)

# ── Tab 1: 部屋の設定 ─────────────────────────────────────────

with tab_room:
    st.subheader("部屋のサイズ")
    st.caption("畳数を選ぶと、一般的なお部屋の大きさが自動で入ります。")

    preset_index = PRESET_OPTIONS.index(st.session_state.room_preset)
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
        st.info(f"設定中: 幅 {rw} cm × 奥行 {rd} cm × 高さ {rh} cm")
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
    st.subheader("部屋の参考写真（任意）")
    st.markdown(
        "共有するときに **「今の部屋」** として一緒に見せるための写真です。"
        "3D空間の形には影響しません。"
    )

    col_cam, col_upload = st.columns(2)

    with col_cam:
        st.markdown("**カメラで撮影**（スマホブラウザ対応）")
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
        pending.append({"label": "カメラ撮影", "data": camera_photo.getvalue()})
    if uploaded_photos:
        for photo in uploaded_photos:
            pending.append({"label": photo.name, "data": photo.getvalue()})

    bc1, bc2 = st.columns(2)
    if bc1.button("写真を記録する", type="primary", disabled=not pending):
        st.session_state.room_photos = pending
        st.rerun()

    if bc2.button("記録した写真をすべて削除", disabled=not st.session_state.room_photos):
        st.session_state.room_photos = []
        st.rerun()

    if st.session_state.room_photos:
        st.success(f"{len(st.session_state.room_photos)} 枚の参考写真を記録中")
        cols = st.columns(min(len(st.session_state.room_photos), 4))
        for i, photo in enumerate(st.session_state.room_photos):
            cols[i % len(cols)].image(
                photo["data"], caption=photo["label"], use_container_width=True
            )
    else:
        st.caption("参考写真はまだ記録されていません。")

# ── Tab 2: 家具の配置 ─────────────────────────────────────────

with tab_layout:
    st.subheader("間取り図で家具を配置")
    st.caption(
        "間取り図をタップして家具を移動できます。"
        "色で家具の種類を区別できます。"
    )
    render_color_legend()

    rw, rd, rh = st.session_state.room_size

    if st.session_state.placed_furniture:
        apply_pending_move_index()

        st.selectbox(
            "移動する家具",
            range(len(st.session_state.placed_furniture)),
            format_func=lambda i: (
                f"{i + 1}. {st.session_state.placed_furniture[i]['name']}"
            ),
            key="move_furniture_select",
        )

        st.markdown("**間取り図**")
        st.caption("下の図をタップすると、選択中の家具がその位置に移動します。")
        fig_2d = build_floor_plan_figure(st.session_state.placed_furniture, rw, rd)
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
                point["x"],
                point["y"],
                item["width_cm"],
                item["depth_cm"],
                rw,
                rd,
            )
            st.session_state.placed_furniture[idx]["position"] = [x, y, 0]
            st.rerun()

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
            idx = get_selected_furniture_index()
            item = normalize_furniture_item(st.session_state.placed_furniture[idx])
            st.session_state.placed_furniture[idx] = {
                **item,
                "rotation": (item["rotation"] + 90) % 360,
            }
            st.rerun()
    else:
        st.info("家具を追加すると、ここに間取り図が表示されます。")

    st.divider()
    st.markdown("**家具を追加**")

    furniture_name = st.selectbox(
        "追加する家具",
        list(FURNITURE_CATALOG.keys()),
        key="furniture_select",
    )

    defaults = FURNITURE_CATALOG[furniture_name]["default_cm"]
    st.markdown("**家具のサイズ（cm）**")
    size_c1, size_c2, size_c3 = st.columns(3)
    add_width_cm = size_c1.number_input(
        "横（幅）",
        min_value=30,
        max_value=400,
        value=int(defaults["width"]),
        step=5,
        key=f"add_furniture_width_{furniture_name}",
    )
    add_depth_cm = size_c2.number_input(
        "縦（奥行）",
        min_value=30,
        max_value=400,
        value=int(defaults["depth"]),
        step=5,
        key=f"add_furniture_depth_{furniture_name}",
    )
    add_height_cm = size_c3.number_input(
        "高さ",
        min_value=30,
        max_value=300,
        value=int(defaults["height"]),
        step=5,
        key=f"add_furniture_height_{furniture_name}",
    )
    st.caption("一般的なサイズが初期値です。実際の商品サイズが分かれば入力してください。")

    bc1, bc2, bc3 = st.columns(3)
    if bc1.button("選択した家具を追加", type="primary", use_container_width=True):
        count = len(st.session_state.placed_furniture)
        st.session_state.placed_furniture.append(
            {
                "name": furniture_name,
                "position": new_furniture_position(count, rw, rd),
                "rotation": 0,
                "width_cm": float(add_width_cm),
                "depth_cm": float(add_depth_cm),
                "height_cm": float(add_height_cm),
            }
        )
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

    if st.session_state.placed_furniture:
        st.markdown("**配置済み家具**")
        for i, raw in enumerate(st.session_state.placed_furniture, 1):
            item = normalize_furniture_item(raw)
            st.text(
                f"{i}. {item['name']} — "
                f"サイズ {item['width_cm']:.0f} × {item['depth_cm']:.0f} × {item['height_cm']:.0f} cm, "
                f"位置 ({item['position'][0]:.0f}, {item['position'][1]:.0f}) cm, "
                f"向き {item['rotation']:.0f} 度"
            )

        st.markdown("**配置済み家具のサイズ変更**")
        edit_idx = st.selectbox(
            "変更する家具",
            range(len(st.session_state.placed_furniture)),
            format_func=lambda i: (
                f"{i + 1}. {st.session_state.placed_furniture[i]['name']}"
            ),
            key="edit_furniture_index",
        )
        edit_item = normalize_furniture_item(st.session_state.placed_furniture[edit_idx])
        edit_c1, edit_c2, edit_c3 = st.columns(3)
        edit_width = edit_c1.number_input(
            "横（幅）",
            min_value=30,
            max_value=400,
            value=int(edit_item["width_cm"]),
            step=5,
            key=f"edit_width_{edit_idx}",
        )
        edit_depth = edit_c2.number_input(
            "縦（奥行）",
            min_value=30,
            max_value=400,
            value=int(edit_item["depth_cm"]),
            step=5,
            key=f"edit_depth_{edit_idx}",
        )
        edit_height = edit_c3.number_input(
            "高さ",
            min_value=30,
            max_value=300,
            value=int(edit_item["height_cm"]),
            step=5,
            key=f"edit_height_{edit_idx}",
        )
        if st.button("この家具のサイズを反映", key="apply_furniture_size"):
            st.session_state.placed_furniture[edit_idx] = {
                **edit_item,
                "width_cm": float(edit_width),
                "depth_cm": float(edit_depth),
                "height_cm": float(edit_height),
            }
            st.rerun()
    else:
        st.info("「選択した家具を追加」を押すと、間取り図の中央に家具が表示されます。")

    st.divider()
    st.subheader("3Dプレビュー")
    room_mesh = create_room(rw, rd, rh)
    fig_layout = build_scene_figure(room_mesh, build_placed_items(st.session_state.placed_furniture))
    st.plotly_chart(fig_layout, use_container_width=True, key="layout_3d_preview")

# ── Tab 3: プレビューと共有 ───────────────────────────────────

with tab_share:
    st.subheader("プレビュー")
    st.caption(
        "左（または上）が実際の部屋の写真、右（または下）が家具を配置した3Dシミュレーションです。"
    )

    rw, rd, rh = st.session_state.room_size
    room_mesh = create_room(rw, rd, rh)
    fig = build_scene_figure(room_mesh, build_placed_items(st.session_state.placed_furniture))

    if st.session_state.room_photos:
        col_photo, col_3d = st.columns(2)
        with col_photo:
            st.markdown("**実際の部屋**")
            for photo in st.session_state.room_photos:
                st.image(photo["data"], caption=photo["label"], use_container_width=True)
        with col_3d:
            st.markdown("**家具配置シミュレーション**")
            st.plotly_chart(fig, use_container_width=True, key="share_3d_with_photo")
    else:
        st.markdown("**家具配置シミュレーション**")
        st.plotly_chart(fig, use_container_width=True, key="share_3d_only")
        st.info(
            "参考写真が未登録です。「1. 部屋の設定」で写真を記録すると、"
            "実際の部屋と3Dシミュレーションを並べて見せられます。"
        )

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
            - 写真・動画からの3D空間の自動復元（フォトグラメトリ）
            - より多くの家具カタログ（カスタムモデルの読み込み）
            - 壁・窓の自動検出
            - 共有リンクの生成
            """
        )
