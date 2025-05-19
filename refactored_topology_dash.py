import os
import time
import logging
import base64
from collections import deque

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.compute import Server
from diagrams.onprem.storage import Ceph
from diagrams.generic.network import Switch

import plotly.graph_objects as go

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc
from dash.dependencies import Input, Output, State

from email_service import send_email_alert_async
from supabase_client import fetch_data_from_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

HEALTH_COLOUR = {
    "healthy":  "success",
    "degraded": "warning",
    "critical": "danger",
    "unknown":  "secondary",
}
NODE_COLOUR = {
    "healthy":  "green",
    "degraded": "orange",
    "critical": "red",
    "unknown":  "gray",
}

alerted_components = set()
change_log      = deque(maxlen=5)
prev_data       = None

ICON_FILES = {
    "server":  "images/Server.png",
    "storage": "images/Storage.png",
    "backup":  "images/Backup.png",
    "switch":  "images/Switch.png",
}

ICON_URIS = {}
for key, path in ICON_FILES.items():
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
            ICON_URIS[key] = f"data:image/png;base64,{b64}"
    except FileNotFoundError:
        logger.warning("Icon not found: %s", path)
        ICON_URIS[key] = None

ASSETS_PNG = os.path.join("assets", "HPE_topology.png")
os.makedirs(os.path.dirname(ASSETS_PNG), exist_ok=True)

def generate_png_topology(data):
    components = {}
    base = os.path.splitext(ASSETS_PNG)[0]

    with Diagram(
        f"{data['private_cloud'].get('name','Private Cloud')} Architecture",
        filename=base, show=False, direction="LR", graph_attr={"dpi":"150"}
    ):
        with Cluster("Compute Nodes"):
            for comp in data["servers"]:
                if comp.get("type") == "KVM":
                    components[comp["id"]] = Server(comp["name"])
        with Cluster("Storage"):
            for comp in data["storage"]:
                if comp.get("type") == "Ceph":
                    components[comp["id"]] = Ceph(comp["name"])
        with Cluster("Network"):
            for comp in data["network_switches"]:
                components[comp["id"]] = Switch(comp["name"])
        with Cluster("Backup"):
            for comp in data["backup"]:
                if comp.get("type") == "NAS":
                    components[comp["id"]] = Ceph(comp["name"])

        seen = set()
        def _connect(items):
            for it in items:
                hid    = it["id"]
                health = it.get("health","unknown")
                color  = NODE_COLOUR.get(health,"gray")

                # one‐time email
                if health=="critical" and hid not in alerted_components:
                    body = (
                        f"Critical Component Alert\n"
                        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"{it['name']} (ID {hid}) is CRITICAL\n"
                    )
                    send_email_alert_async(subject=f"Critical Alert: {it['name']}", body=body)
                    alerted_components.add(hid)

                for c in it.get("connected_switches", []):
                    sid = c["switch_id"]
                    key = tuple(sorted((hid, sid)))
                    if hid in components and sid in components and key not in seen:
                        components[hid] >> Edge(
                            label=c.get("port","N/A"), color=color
                        ) >> components[sid]
                        seen.add(key)

        _connect(data["servers"])
        _connect(data["storage"])
        _connect(data["backup"])

    logger.info("✅ PNG topology diagram generated.")

def build_network_figure(data):
    fig = go.Figure()
    node_positions = {}
    layout_images  = []

    left_x, right_x = 0.1, 0.9
    span = 0.8
    left_nodes  = data["servers"] + data["storage"] + data["backup"]
    right_nodes = data["network_switches"]

    def img_for(node):
        if "cpu_utilization" in node:
            return ICON_URIS["server"]
        t = node.get("type","").lower()
        if t=="nas":
            return ICON_URIS["backup"]
        if t=="ceph":
            return ICON_URIS["storage"]
        return ICON_URIS["storage"]

    # Left column
    for i, node in enumerate(left_nodes):
        y = 0.9 - i*(span/max(1,len(left_nodes)))
        node_positions[node["id"]] = (left_x, y)
        fig.add_trace(go.Scatter(
            x=[left_x], y=[y], mode="markers",
            marker=dict(size=18, color=NODE_COLOUR.get(node.get("health","gray"))),
            hoverinfo="text",
            hovertext=(
                f"<b>{node['name']}</b><br>"
                f"ID: {node['id']}<br>"
                f"Type: {node.get('type','N/A')}<br>"
                f"Role: {node.get('role','N/A')}<br>"
                f"Health: {node.get('health','unknown')}"
            ),
            customdata=[node], showlegend=False
        ))
        layout_images.append(dict(
            source=img_for(node), xref="x", yref="y",
            x=left_x, y=y+0.03,
            sizex=0.08, sizey=0.08,
            xanchor="center", yanchor="middle", layer="above"
        ))

    # Right column
    for i, sw in enumerate(right_nodes):
        y = 0.9 - i*(span/max(1,len(right_nodes)))
        node_positions[sw["id"]] = (right_x, y)
        fig.add_trace(go.Scatter(
            x=[right_x], y=[y], mode="markers",
            marker=dict(size=18, color=NODE_COLOUR.get(sw.get("health","gray"))),
            hoverinfo="text",
            hovertext=(
                f"<b>{sw['name']}</b><br>"
                f"ID: {sw['id']}<br>"
                f"Type: {sw.get('switch_type','N/A')}<br>"
                f"Role: {sw.get('role','N/A')}<br>"
                f"Health: {sw.get('health','unknown')}"
            ),
            customdata=[sw], showlegend=False
        ))
        layout_images.append(dict(
            source=ICON_URIS["switch"], xref="x", yref="y",
            x=right_x, y=y+0.03,
            sizex=0.08, sizey=0.08,
            xanchor="center", yanchor="middle", layer="above"
        ))

    # Edges
    for node in left_nodes:
        nid, health = node["id"], node.get("health","unknown")
        for c in node.get("connected_switches", []):
            sid = c["switch_id"]
            if nid in node_positions and sid in node_positions:
                x0,y0 = node_positions[nid]
                x1,y1 = node_positions[sid]
                fig.add_trace(go.Scatter(
                    x=[x0,x1], y=[y0,y1], mode="lines",
                    line=dict(color=NODE_COLOUR[health], width=2),
                    hoverinfo="none", showlegend=False
                ))

    fig.update_layout(
        images=layout_images,
        title="Topology",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=20,r=20,t=40,b=20),
        plot_bgcolor="white", paper_bgcolor="white",
        height=550
    )
    return fig


def detect_changes(old, new):
    msgs = []
    if old is None:
        return ["Initial load"]
    for key in ("servers","storage","backup","network_switches"):
        oidx = {x["id"]:x for x in old.get(key,[])}
        nidx = {x["id"]:x for x in new.get(key,[])}
        for nid,nitem in nidx.items():
            if nid not in oidx:
                msgs.append(f"Added {key[:-1]}: {nitem['name']}")
        for oid,oitem in oidx.items():
            if oid not in nidx:
                msgs.append(f"Removed {key[:-1]}: {oitem['name']}")
        for nid,nitem in nidx.items():
            if nid in oidx:
                oh = oidx[nid].get("health","unknown")
                nh = nitem.get("health","unknown")
                if oh != nh:
                    msgs.append(f"{nitem['name']} health: {oh} → {nh}")
    return msgs or ["No changes"]


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CERULEAN])
server = app.server

app.layout = dbc.Container(fluid=True, children=[
    dbc.Row(dbc.Col(html.H2("HPE Topology Dashboard"), className="text-center my-3")),

    # Summary panel
    dbc.Row(dbc.Col(dbc.Button("Summary", id="btn-summary", color="info",
                               className="mb-2", n_clicks=0), width=12)),
    dbc.Row(dbc.Col(dbc.Collapse(id="collapse-summary", is_open=True,
        children=html.Div(id="summary-cards", style={"display":"flex","gap":"1rem"})
    ), width=8)),

    dbc.Row(dbc.Col(dbc.Button("Topology & Details", id="btn-topology", color="info",
                               className="mb-2", n_clicks=0), width=12)),
    dbc.Row(dbc.Col(dbc.Collapse(id="collapse-topology", is_open=True,
        children=[
          dbc.Row([
              dbc.Col(dcc.Graph(id="network-graph"), md=8),
              dbc.Col(html.Div("Click a node for details",
                       id="node-details", className="border p-3"), md=4)
          ])
        ]
    ), width=12)),

    dbc.Row(dbc.Col(dbc.Button("Change Log", id="btn-changelog", color="info",
                               className="mb-2", n_clicks=0), width=12)),
    dbc.Row(dbc.Col(dbc.Collapse(id="collapse-changelog", is_open=True,
        children=html.Ul(id="change-log",
          style={"maxHeight":"140px","overflowY":"auto",
                 "background":"#f8f9fa","padding":"10px","border":"1px solid #dee2e6"}
        )
    ), width=12)),

    # Interval
    dcc.Interval(id="interval", interval=10_000, n_intervals=0)
])

@app.callback(
    Output("collapse-summary","is_open"),
    Input("btn-summary","n_clicks"),
    State("collapse-summary","is_open")
)
def toggle_summary(n, is_open):
    return not is_open if n else is_open

@app.callback(
    Output("collapse-topology","is_open"),
    Input("btn-topology","n_clicks"),
    State("collapse-topology","is_open")
)
def toggle_topology(n, is_open):
    return not is_open if n else is_open

@app.callback(
    Output("collapse-changelog","is_open"),
    Input("btn-changelog","n_clicks"),
    State("collapse-changelog","is_open")
)
def toggle_changelog(n, is_open):
    return not is_open if n else is_open

@app.callback(
    Output("network-graph","figure"),
    Output("change-log","children"),
    Output("summary-cards","children"),
    Input("interval","n_intervals")
)
def refresh(n):
    global prev_data

    data = fetch_data_from_supabase() or {}
    msgs = detect_changes(prev_data, data)
    ts   = time.strftime("%H:%M:%S")
    for m in msgs:
        change_log.appendleft(f"{ts} — {m}")
    prev_data = data

    generate_png_topology(data)
    fig = build_network_figure(data)

    log_items = [html.Li(msg) for msg in change_log]

    all_nodes = data["servers"] + data["storage"] + data["backup"] + data["network_switches"]
    total = len(all_nodes)
    counts = {h:0 for h in HEALTH_COLOUR}
    for nd in all_nodes:
        counts[nd.get("health","unknown")] += 1

    cards = []
    for label, key in [
        ("Total Nodes","total"),
        ("Healthy","healthy"),
        ("Degraded","degraded"),
        ("Critical","critical")
    ]:
        if key=="total":
            cnt = total
            pct = 100
        else:
            cnt = counts[key]
            pct = int((cnt/total)*100) if total>0 else 0

        color = HEALTH_COLOUR.get(key,"secondary")
        cards.append(dbc.Card(
            dbc.CardBody([
                html.H6(label, className="card-title"),
                html.H4(str(cnt), className="card-text"),
                dbc.Progress(value=pct, color=color, striped=True, style={"height":"8px"})
            ]),
            color=color, inverse=(key!="total"), style={"flex":"1"}
        ))

    summary = html.Div(cards, style={"display":"flex","gap":"1rem"})

    return fig, log_items, summary

@app.callback(
    Output("node-details","children"),
    Input("network-graph","clickData")
)
def show_details(clickData):
    if not clickData or "points" not in clickData:
        return "Click a node to see details"
    node = clickData["points"][0].get("customdata", {})
    if not node:
        return "No details available"

    rows = []
    for key in ("name","id","type","role","health","power_status","location"):
        if key in node:
            rows.append(html.P(f"{key.title()}: {node[key]}"))
    for opt in ("cpu_utilization","ip_address","mac"):
        if opt in node:
            rows.append(html.P(f"{opt.replace('_',' ').title()}: {node[opt]}"))

    conns = node.get("connected_switches", [])
    if conns:
        rows.append(html.H6("Connections:"))
        for c in conns:
            rows.append(html.P(f"Switch {c['switch_id']} port {c['port']}"))

    return rows

if __name__ == "__main__":
    prev_data = fetch_data_from_supabase() or {}
    generate_png_topology(prev_data)

    logger.info("Starting Dash server at http://127.0.0.1:8050")
    app.run(debug=False)
