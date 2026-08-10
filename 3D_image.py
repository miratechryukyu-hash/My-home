import json

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import trimesh
from streamlit_drawable_canvas import st_canvas

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


FURNITURE_CATALOG = {
    "2段ベッド": {
        "factory": create_bunk_bed,
        "color": "#8B7355",
        "default_cm": {"width": 100, "depth": 200, "height": 220},
    },
    "シングルベッド": {
        "factory": create_single_bed,
        "color": "#A0826D",
        "default_cm": {"width": 100, "depth": 200, "height": 50},
    },
    "デスク": {
        "factory": create_desk,
        "color": "#C4A882",
        "default_cm": {"width": 120, "depth": 60, "height": 75},
    },
    "ソファ": {
        "factory": create_sofa,
        "color": "#6B8E9B",
        "default_cm": {"width": 180, "depth": 80, "height": 85},
    },
}


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
        mesh = apply_transform(
            catalog["factory"](),
            cfg["position"],
            cfg["rotation"],
            scale_xyz,
        )
        placed_items.append(
            {"mesh": mesh, "color": catalog["color"], "name": cfg["name"]}
        )
    return placed_items


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
        fw = item["width_cm"]
        fd = item["depth_cm"]
        cx, cy = room_cm_to_canvas(
            item["position"], room_width_cm, room_depth_cm, px_per_cm
        )
        w_px = fw * px_per_cm
        h_px = fd * px_per_cm
        objects.append(
            {
                "type": "rect",
                "left": cx - w_px / 2,
                "top": cy - h_px / 2,
                "width": w_px,
                "height": h_px,
                "scaleX": 1,
                "scaleY": 1,
                "angle": item["rotation"],
                "fill": catalog["color"],
                "opacity": 0.88,
                "stroke": "#333333",
                "strokeWidth": 2,
                "name": f"{item['name']}::{index}",
            }
        )
        label = f"{item['name']}\n{fw:.0f}×{fd:.0f}cm"
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
    if "canvas_version" not in st.session_state:
        st.session_state.canvas_version = 0
    if "last_canvas_room_size" not in st.session_state:
        st.session_state.last_canvas_room_size = None
    if "room_size" not in st.session_state:
        st.session_state.room_size = ROOM_PRESETS["6畳（約 364 × 273 cm）"]
    elif st.session_state.room_size[0] < 50:
        st.session_state.room_size = tuple(v * 100 for v in st.session_state.room_size)
    if "room_preset" not in st.session_state:
        st.session_state.room_preset = "6畳（約 364 × 273 cm）"


def bump_canvas_version():
    st.session_state.canvas_version += 1


def sync_canvas_to_session(canvas_json, room_width_cm, room_depth_cm):
    """Canvas の内容を session_state に反映（空データで上書きしない）"""
    current = [normalize_furniture_item(item) for item in st.session_state.placed_furniture]
    parsed = parse_canvas_furniture(canvas_json, room_width_cm, room_depth_cm, current)
    if parsed is None:
        return

    if not parsed and current:
        return

    if json.dumps(parsed, ensure_ascii=False) != json.dumps(current, ensure_ascii=False):
        st.session_state.placed_furniture = parsed


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
        bump_canvas_version()

    if selected_preset != "自分で入力（cm）":
        new_size = ROOM_PRESETS[selected_preset]
        if st.session_state.room_size != new_size:
            bump_canvas_version()
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
        if st.session_state.room_size != new_size:
            bump_canvas_version()
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
        "家具をタッチしてドラッグすると位置を変更できます。"
        "選択した状態で角を触るとサイズ変更、上の丸を触ると回転できます。"
    )

    rw, rd, rh = st.session_state.room_size
    if st.session_state.last_canvas_room_size != (rw, rd, rh):
        bump_canvas_version()
        st.session_state.last_canvas_room_size = (rw, rd, rh)

    px_per_cm, canvas_w, canvas_h = canvas_scale(rw, rd)

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
        st.session_state.placed_furniture.append(
            {
                "name": furniture_name,
                "position": [0, 0, 0],
                "rotation": 0,
                "width_cm": float(add_width_cm),
                "depth_cm": float(add_depth_cm),
                "height_cm": float(add_height_cm),
            }
        )
        bump_canvas_version()
        st.rerun()

    if bc2.button("最後の家具を削除", use_container_width=True):
        if st.session_state.placed_furniture:
            st.session_state.placed_furniture.pop()
            bump_canvas_version()
            st.rerun()

    if bc3.button("すべてクリア", use_container_width=True):
        st.session_state.placed_furniture = []
        bump_canvas_version()
        st.rerun()

    initial_drawing = build_canvas_drawing(st.session_state.placed_furniture, rw, rd)
    canvas_result = st_canvas(
        fill_color="rgba(0, 0, 0, 0)",
        stroke_width=0,
        background_color="#FFFFFF",
        update_streamlit=True,
        height=canvas_h,
        width=canvas_w,
        drawing_mode="transform",
        initial_drawing=initial_drawing,
        display_toolbar=False,
        key=f"floor_plan_canvas_v{st.session_state.canvas_version}",
    )

    if canvas_result.json_data is not None:
        sync_canvas_to_session(canvas_result.json_data, rw, rd)

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
            bump_canvas_version()
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
