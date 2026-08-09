import streamlit as st
import trimesh
import plotly.graph_objects as go
import tempfile

st.title("🗿 OBJ / STL 3Dモデル表示 (Trimesh)")

uploaded_file = st.file_uploader("3Dモデル (.obj / .stl) をアップロード", type=["obj", "stl"])

if uploaded_file is not None:
    # 一時ファイルとして保存してTrimeshで読み込み
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_path = tmp_file.name

    # モデルのロード
    mesh = trimesh.load(tmp_path)

    # 頂点 (Vertices) と 面 (Faces) を取得
    vertices = mesh.vertices
    faces = mesh.faces

    # Plotly Mesh3d の作成
    fig = go.Figure(data=[
        go.Mesh3d(
            x=vertices[:, 0],
            y=vertices[:, 1],
            z=vertices[:, 2],
            i=faces[:, 0],
            j=faces[:, 1],
            k=faces[:, 2],
            color='lightblue',
            opacity=0.9
        )
    ])

    fig.update_layout(
        scene=dict(aspectmode='data'),
        margin=dict(l=0, r=0, b=0, t=0)
    )

    st.plotly_chart(fig, use_container_width=True)
