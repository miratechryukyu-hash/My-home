import numpy as np
import plotly.graph_objects as go
import streamlit as st
import trimesh

st.set_page_config(
    page_title="自宅レイアウトイメージ",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 家具メッシュ生成 ──────────────────────────────────────────


def _box(extents, color="lightgray"):
    return trimesh.creation.box(extents=extents)


def create_bunk_bed():
    """簡易的な2段ベッド（ボックス組み合わせ）"""
    parts = []
    bed_w, bed_d, bed_h = 1.0, 2.0, 0.35
    gap = 0.9

    for level, z in enumerate([bed_h / 2, bed_h / 2 + gap]):
        mattress = _box([bed_w, bed_d, bed_h])
        mattress.apply_translation([0, 0, z])
        parts.append(mattress)

        leg_positions = [
            (-bed_w / 2 + 0.05, -bed_d / 2 + 0.05, z - bed_h / 2),
            (bed_w / 2 - 0.05, -bed_d / 2 + 0.05, z - bed_h / 2),
            (-bed_w / 2 + 0.05, bed_d / 2 - 0.05, z - bed_h / 2),
            (bed_w / 2 - 0.05, bed_d / 2 - 0.05, z - bed_h / 2),
        ]
        for pos in leg_positions:
            leg = _box([0.08, 0.08, z])
            leg.apply_translation(pos)
            parts.append(leg)

    ladder = _box([0.08, 0.08, gap + bed_h])
    ladder.apply_translation([bed_w / 2 + 0.1, 0, (gap + bed_h) / 2])
    parts.append(ladder)

    return trimesh.util.concatenate(parts)


def create_single_bed():
    bed_w, bed_d, bed_h = 1.0, 2.0, 0.35
    mattress = _box([bed_w, bed_d, bed_h])
    mattress.apply_translation([0, 0, bed_h / 2])
    return mattress


def create_desk():
    top = _box([1.2, 0.6, 0.04])
    top.apply_translation([0, 0, 0.74])
    leg_h = 0.72
    legs = []
    for x, y in [(-0.55, -0.25), (0.55, -0.25), (-0.55, 0.25), (0.55, 0.25)]:
        leg = _box([0.06, 0.06, leg_h])
        leg.apply_translation([x, y, leg_h / 2])
        legs.append(leg)
    return trimesh.util.concatenate([top, *legs])


def create_sofa():
    seat = _box([1.8, 0.8, 0.4])
    seat.apply_translation([0, 0, 0.2])
    back = _box([1.8, 0.15, 0.7])
    back.apply_translation([0, -0.325, 0.55])
    return trimesh.util.concatenate([seat, back])


FURNITURE_CATALOG = {
    "2段ベッド": {"factory": create_bunk_bed, "color": "#8B7355"},
    "シングルベッド": {"factory": create_single_bed, "color": "#A0826D"},
    "デスク": {"factory": create_desk, "color": "#C4A882"},
    "ソファ": {"factory": create_sofa, "color": "#6B8E9B"},
}


def create_room(width, depth, height):
    """部屋をワイヤーフレーム風の薄いボックスで表現"""
    floor = _box([width, depth, 0.02])
    floor.apply_translation([0, 0, 0.01])
    parts = [floor]

    wall_specs = [
        ([0.02, depth, height], [-width / 2 + 0.01, 0, height / 2]),
        ([0.02, depth, height], [width / 2 - 0.01, 0, height / 2]),
        ([width, 0.02, height], [0, -depth / 2 + 0.01, height / 2]),
        ([width, 0.02, height], [0, depth / 2 - 0.01, height / 2]),
    ]
    for extents, pos in wall_specs:
        wall = _box(extents)
        wall.apply_translation(pos)
        parts.append(wall)

    return trimesh.util.concatenate(parts)


def apply_transform(mesh, position, rotation_y_deg, scale):
    m = mesh.copy()
    if scale != 1.0:
        m.apply_scale(scale)
    if rotation_y_deg:
        rot = trimesh.transformations.rotation_matrix(
            np.radians(rotation_y_deg), [0, 0, 1]
        )
        m.apply_transform(rot)
    m.apply_translation(position)
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


def build_scene_figure(room_mesh, placed_items, room_size):
    traces = [
        mesh_to_trace(room_mesh, "#E8E4DF", "部屋", opacity=0.35),
    ]
    for item in placed_items:
        traces.append(
            mesh_to_trace(item["mesh"], item["color"], item["name"], opacity=0.9)
        )

    w, d, h = room_size
    fig = go.Figure(data=traces)
    fig.update_layout(
        title="3Dレイアウトプレビュー",
        scene=dict(
            aspectmode="data",
            xaxis_title="幅 (m)",
            yaxis_title="奥行 (m)",
            zaxis_title="高さ (m)",
            camera=dict(eye=dict(x=1.6, y=-1.8, z=1.2)),
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


# ── UI ────────────────────────────────────────────────────────

st.title("🏠 自宅レイアウトイメージ共有")
st.caption(
    "スマホで部屋を撮影 → 家具を配置 → イメージを共有するためのアプリです。"
)

tab_capture, tab_layout, tab_share = st.tabs(
    ["📷 1. 空間の記録", "🛋️ 2. 家具の配置", "📤 3. プレビューと共有"]
)

# ── Tab 1: 空間の記録 ─────────────────────────────────────────

with tab_capture:
    st.subheader("部屋の写真・動画を記録")
    st.info(
        "**現在のバージョン:** 撮影データは参考画像として保存します。"
        "写真・動画から自動で3D空間を復元する機能は今後追加予定です。"
        "その間は、部屋のサイズを入力して簡易3D空間を作成します。"
    )

    col_cam, col_upload = st.columns(2)

    with col_cam:
        st.markdown("**カメラで撮影**（スマホブラウザ対応）")
        camera_photo = st.camera_input("部屋の写真を撮る")

    with col_upload:
        st.markdown("**ファイルからアップロード**")
        photos = st.file_uploader(
            "写真（複数可）",
            type=["jpg", "jpeg", "png", "heic"],
            accept_multiple_files=True,
        )
        video = st.file_uploader(
            "動画（1本）",
            type=["mp4", "mov", "webm"],
        )

    captured = []
    if camera_photo is not None:
        captured.append(("カメラ撮影", camera_photo))
    if photos:
        for p in photos:
            captured.append((p.name, p))

    if captured:
        st.success(f"{len(captured)} 枚の写真を記録しました")
        cols = st.columns(min(len(captured), 4))
        for i, (label, img) in enumerate(captured):
            cols[i % len(cols)].image(img, caption=label, use_container_width=True)

    if video is not None:
        st.success(f"動画を記録しました: {video.name}")
        st.video(video)
        st.caption("動画からの3D復元は準備中です。現時点では参考資料として保存されます。")

    st.divider()
    st.subheader("部屋のサイズ（おおよそ）")
    c1, c2, c3 = st.columns(3)
    room_width = c1.number_input("幅 (m)", min_value=2.0, max_value=15.0, value=4.0, step=0.5)
    room_depth = c2.number_input("奥行 (m)", min_value=2.0, max_value=15.0, value=3.5, step=0.5)
    room_height = c3.number_input("高さ (m)", min_value=2.0, max_value=4.0, value=2.4, step=0.1)

    st.session_state["room_size"] = (room_width, room_depth, room_height)

# ── Tab 2: 家具の配置 ─────────────────────────────────────────

with tab_layout:
    st.subheader("サンプル家具を部屋に配置")

    room_size = st.session_state.get("room_size", (4.0, 3.5, 2.4))
    rw, rd, rh = room_size

    col_sel, col_ctrl = st.columns([1, 2])

    with col_sel:
        furniture_name = st.selectbox(
            "家具を選ぶ",
            list(FURNITURE_CATALOG.keys()),
        )
        st.markdown(f"**選択中:** {furniture_name}")

    with col_ctrl:
        st.markdown("**位置・向き**")
        c1, c2, c3, c4 = st.columns(4)
        pos_x = c1.slider("左右 (m)", -rw / 2 + 0.5, rw / 2 - 0.5, 0.0, 0.1)
        pos_y = c2.slider("前後 (m)", -rd / 2 + 0.5, rd / 2 - 0.5, 0.0, 0.1)
        rotation = c3.slider("回転 (°)", 0, 360, 0, 15)
        scale = c4.slider("サイズ", 0.5, 2.0, 1.0, 0.1)

    if "placed_furniture" not in st.session_state:
        st.session_state.placed_furniture = []

    bc1, bc2, bc3 = st.columns(3)
    if bc1.button("この家具を追加", type="primary", use_container_width=True):
        st.session_state.placed_furniture.append(
            {
                "name": furniture_name,
                "position": [pos_x, pos_y, 0],
                "rotation": rotation,
                "scale": scale,
            }
        )
        st.rerun()

    if bc2.button("最後の家具を削除", use_container_width=True):
        if st.session_state.placed_furniture:
            st.session_state.placed_furniture.pop()
            st.rerun()

    if bc3.button("すべてクリア", use_container_width=True):
        st.session_state.placed_furniture = []
        st.rerun()

    if st.session_state.placed_furniture:
        st.markdown("**配置済み家具**")
        for i, item in enumerate(st.session_state.placed_furniture, 1):
            st.text(
                f"{i}. {item['name']} — "
                f"位置 ({item['position'][0]:.1f}, {item['position'][1]:.1f}), "
                f"回転 {item['rotation']}°, サイズ {item['scale']:.1f}x"
            )

# ── Tab 3: プレビューと共有 ───────────────────────────────────

with tab_share:
    st.subheader("3Dレイアウトのプレビュー")

    room_size = st.session_state.get("room_size", (4.0, 3.5, 2.4))
    room_mesh = create_room(*room_size)

    placed_items = []
    for cfg in st.session_state.get("placed_furniture", []):
        catalog = FURNITURE_CATALOG[cfg["name"]]
        mesh = apply_transform(
            catalog["factory"](),
            cfg["position"],
            cfg["rotation"],
            cfg["scale"],
        )
        placed_items.append(
            {"mesh": mesh, "color": catalog["color"], "name": cfg["name"]}
        )

    fig = build_scene_figure(room_mesh, placed_items, room_size)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("イメージを共有")
    st.markdown(
        "下のボタンで画像を保存し、LINE・メールなどで家族や業者と共有できます。"
    )

    try:
        img_bytes = fig.to_image(format="png", width=1200, height=800, scale=2)
        st.download_button(
            label="📥 レイアウト画像をダウンロード（PNG）",
            data=img_bytes,
            file_name="home_layout.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
    except Exception:
        st.warning(
            "画像の書き出しには kaleido が必要です。"
            "ターミナルで `pip install kaleido` を実行してください。"
            "それまでは画面上の3Dビューをスクリーンショットで共有できます。"
        )

    with st.expander("今後追加予定の機能"):
        st.markdown(
            """
            - 📸 **写真・動画からの3D空間復元**（フォトグラメトリ）
            - 🪑 **より多くの家具カタログ**（カスタムモデルの読み込み）
            - 📐 **壁・窓の自動検出**
            - 🔗 **共有リンクの生成**
            """
        )
