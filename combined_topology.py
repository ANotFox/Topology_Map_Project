import os
import time
import threading
import logging
from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.compute import Server
from diagrams.onprem.network import Nginx
from diagrams.onprem.security import Vault
from diagrams.onprem.storage import Ceph
from diagrams.generic.network import Switch, Router
import smtplib
from email.message import EmailMessage
import ssl
import requests
import plotly.graph_objects as go
import plotly.io as pio
import webbrowser

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = "https://xpchztgrhfhgtcekazan.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwY2h6dGdyaGZoZ3RjZWthemFuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDUxNTY3MTUsImV4cCI6MjA2MDczMjcxNX0.VUKKlhtXgZdr2G4U-CGOjHH6TgugrPyg0cFzePzC4Q8"

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = "dm409@snu.edu.in"
APP_PASSWORD = "mdsrfmvmwjhdznkd"

# Health Status Colour Mapping
health_colour_map = {
    "healthy": "green",
    "degraded": "orange",
    "critical": "red",
    "unknown": "gray"
}

alerted_components = set()

# --- Data Fetching ---
def fetch_table(table_name):
    url = f"{SUPABASE_URL}/rest/v1/{table_name}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, params={"select": "*"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching {table_name} from Supabase: {e}")
        return []

def fetch_data_from_supabase():
    try:
        private_cloud = fetch_table('private_cloud')
        private_cloud = private_cloud[0] if private_cloud else {}
        servers = fetch_table('servers')
        network_switches = fetch_table('network_switches')
        storage = fetch_table('storage')
        backup = fetch_table('backup')
        server_connections = fetch_table('server_connected_switches')
        storage_connections = fetch_table('storage_connected_switches')
        backup_connections = fetch_table('backup_connected_switches')
        network_connections = fetch_table('network_connected_components')

        for server in servers:
            server["connected_switches"] = []
            for conn in server_connections:
                if conn.get("server_id") == server.get("id"):
                    server["connected_switches"].append({"switch_id": conn["switch_id"], "port": conn["port"]})
        for store in storage:
            store["connected_switches"] = []
            for conn in storage_connections:
                if conn.get("storage_id") == store.get("id"):
                    store["connected_switches"].append({"switch_id": conn["switch_id"], "port": conn["port"]})
        for bak in backup:
            bak["connected_switches"] = []
            for conn in backup_connections:
                if conn.get("backup_id") == bak.get("id"):
                    bak["connected_switches"].append({"switch_id": conn["switch_id"], "port": conn["port"]})
        for switch in network_switches:
            switch["connected_components"] = {}
            for conn in network_connections:
                if conn.get("switch_id") == switch.get("id"):
                    switch["connected_components"][conn["port"]] = conn["component_id"]
        return {
            "private_cloud": private_cloud,
            "servers": servers,
            "network_switches": network_switches,
            "storage": storage,
            "backup": backup
        }
    except Exception as e:
        logger.error(f"Error fetching data from Supabase: {e}")
        return None

# --- Email Alert ---
def send_email_alert_async(subject, body):
    def _send_email():
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS
        msg.set_content(body)
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(EMAIL_ADDRESS, APP_PASSWORD)
                server.send_message(msg)
                logger.info("✅ Email alert sent successfully")
        except Exception as e:
            logger.error(f"❌ Failed to send email: {str(e)}")
    threading.Thread(target=_send_email, daemon=True).start()

# --- PNG Diagram Generation (with Alerts) ---
def generate_png_topology(data):
    components = {}
    diagram_path = "HPE_topology"
    with Diagram(
        f"{data['private_cloud'].get('name', 'Private Cloud')} Architecture", 
        filename=diagram_path, 
        show=False, 
        direction="LR", 
        graph_attr={"dpi": "150"}
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
        processed_connections = set()
        def process_connections(items, item_type):
            for item in items:
                item_id = item["id"]
                health_status = item.get("health", "unknown")
                edge_color = health_colour_map.get(health_status, "gray")
                connection_type = item.get("connection_type", "unknown")
                if health_status == "critical" and item_id not in alerted_components:
                    detailed_body = f"""
Critical Component Alert
Time: {time.strftime('%Y-%m-%d %H:%M:%S')}
Component: {item['name']} (ID: {item['id']})
Type: {item.get('type', 'N/A')}
Role: {item.get('role', 'N/A')}
Health: CRITICAL
Power: {item.get('power_status', 'N/A')}
Location: {item.get('location', 'N/A')}
"""
                    send_email_alert_async(
                        subject=f"Critical Alert: {item['name']}",
                        body=detailed_body
                    )
                    alerted_components.add(item_id)
                for conn in item.get("connected_switches", []):
                    switch_id = conn["switch_id"]
                    if switch_id in components and item_id in components:
                        connection_tuple = tuple(sorted([item_id, switch_id]))
                        if connection_tuple not in processed_connections:
                            components[item_id] >> Edge(
                                label=f"{connection_type} ({conn['port']})", 
                                color=edge_color
                            ) >> components[switch_id]
                            processed_connections.add(connection_tuple)
        process_connections(data["servers"], "server")
        process_connections(data["storage"], "storage")
        process_connections(data["backup"], "backup")
    logger.info("PNG topology diagram generated.")

# --- Interactive HTML Topology Generation ---
def generate_interactive_topology(data):
    output_path = "HPE_topology.html"
    fig = go.Figure()
    node_positions = {}
    images_to_add = []

    left_x = 0.1
    right_x = 0.9
    y_step = 0.15

    # Place all non-switch nodes on the left
    left_nodes = data["servers"] + data["storage"] + data["backup"]
    for i, node in enumerate(left_nodes):
        y = 0.9 - i * y_step
        node_positions[node["id"]] = (left_x, y)
        if "cpu_utilization" in node:  # server
            hover_text = f"""
<b>{node['name']}</b><br>ID: {node['id']}<br>Type: {node['type']}<br>Role: {node['role']}<br>Health: {node['health']}<br>Power: {node['power_status']}<br>CPU: {node.get('cpu_utilization', 'N/A')}<br>MAC: {node.get('mac', 'N/A')}<br>Location: {node.get('location', 'N/A')}<br>IP: {node.get('ip_address', 'N/A')}"""
            image_source = "images/Server.png"
        elif node.get("type", "").lower() == "nas":
            hover_text = f"""
<b>{node['name']}</b><br>ID: {node['id']}<br>Type: {node['type']}<br>Role: {node['role']}<br>Health: {node['health']}<br>Power: {node.get('power_status', 'N/A')}<br>MAC: {node.get('mac', 'N/A')}<br>Location: {node.get('location', 'N/A')}"""
            image_source = "images/Backup.png"
        else:  # storage
            hover_text = f"""
<b>{node['name']}</b><br>ID: {node['id']}<br>Type: {node['type']}<br>Role: {node['role']}<br>Health: {node['health']}<br>Power: {node['power_status']}<br>MAC: {node.get('mac', 'N/A')}<br>Location: {node.get('location', 'N/A')}"""
            image_source = "images/Storage.png"
        fig.add_trace(go.Scatter(
            x=[left_x], y=[y], mode='markers+text', name=node["name"], text=[node["name"]],
            textposition="bottom center",
            marker=dict(size=30, color='rgba(0,0,0,0)'),
            hovertext=hover_text,
            hoverinfo='text',
            showlegend=True
        ))
        images_to_add.append(dict(
            source=image_source,
            xref="x", yref="y",
            x=left_x, y=y+0.03,
            sizex=0.06, sizey=0.06,
            xanchor="center", yanchor="middle",
            layer="above"
        ))

    # Place all switches on the right
    for i, switch in enumerate(data["network_switches"]):
        y = 0.9 - i * y_step
        node_positions[switch["id"]] = (right_x, y)
        hover_text = f"""
<b>{switch['name']}</b><br>ID: {switch['id']}<br>Type: {switch.get('switch_type', 'N/A')}<br>Role: {switch.get('role', 'N/A')}<br>Health: {switch['health']}<br>Power: {switch.get('power_status', 'N/A')}<br>MAC: {switch.get('mac', 'N/A')}<br>Location: {switch.get('location', 'N/A')}"""
        fig.add_trace(go.Scatter(
            x=[right_x], y=[y], mode='markers+text', name=switch["name"], text=[switch["name"]],
            textposition="bottom center",
            marker=dict(size=30, color='rgba(0,0,0,0)'),
            hovertext=hover_text,
            hoverinfo='text',
            showlegend=True
        ))
        images_to_add.append(dict(
            source="images/Switch.png",
            xref="x", yref="y",
            x=right_x, y=y+0.03,
            sizex=0.06, sizey=0.06,
            xanchor="center", yanchor="middle",
            layer="above"
        ))

    # Uncommenting this is adding Backup-1 again (need to look at it again)
    # for i, backup in enumerate(data["backup"]):
    #     x = 0.5  # Backup column (middle)
    #     y = 0.9 - (i * 0.18)
    #     node_positions[backup["id"]] = (x, y)
    #     hover_text = f"""
    # <b>{backup['name']}</b><br>ID: {backup['id']}<br>Type: {backup['type']}<br>Role: {backup['role']}<br>Health: {backup['health']}<br>Power: {backup.get('power_status', 'N/A')}<br>MAC: {backup.get('mac', 'N/A')}<br>Location: {backup.get('location', 'N/A')}"""
    #     fig.add_trace(go.Scatter(
    #         x=[x], y=[y], mode='markers+text', name=backup["name"], text=[backup["name"]],
    #         textposition="bottom center",
    #         marker=dict(
    #             size=30,
    #             color='rgba(0,0,0,0)'
    #         ),
    #         hovertext=hover_text,
    #         hoverinfo='text',
    #         showlegend=True
    #     ))
    #     images_to_add.append(dict(
    #         source="images/Backup.png",
    #         xref="x", yref="y",
    #         x=x, y=y+0.03,
    #         sizex=0.06, sizey=0.06,
    #         xanchor="center", yanchor="middle",
    #         layer="above"
    #     ))

    # Add edges (connections)
    for server in data["servers"]:
        for conn in server.get("connected_switches", []):
            switch_id = conn["switch_id"]
            port = conn["port"]
            if server["id"] in node_positions and switch_id in node_positions:
                x0, y0 = node_positions[server["id"]]
                x1, y1 = node_positions[switch_id]
                fig.add_trace(go.Scatter(
                    x=[x0, x1], y=[y0, y1], mode='lines',
                    line=dict(color=health_colour_map.get(server["health"], "gray"), width=3),
                    name=f"{server['name']} → {switch_id}",
                    text=f"Port: {port}",
                    hoverinfo='text',
                    showlegend=False
                ))

    for storage in data["storage"]:
        for conn in storage.get("connected_switches", []):
            switch_id = conn["switch_id"]
            port = conn["port"]
            if storage["id"] in node_positions and switch_id in node_positions:
                x0, y0 = node_positions[storage["id"]]
                x1, y1 = node_positions[switch_id]
                fig.add_trace(go.Scatter(
                    x=[x0, x1], y=[y0, y1], mode='lines',
                    line=dict(color=health_colour_map.get(storage["health"], "gray"), width=3),
                    name=f"{storage['name']} → {switch_id}",
                    text=f"Port: {port}",
                    hoverinfo='text', showlegend=False))

    for backup in data["backup"]:
        for conn in backup.get("connected_switches", []):
            switch_id = conn["switch_id"]
            port = conn["port"]
            if backup["id"] in node_positions and switch_id in node_positions:
                x0, y0 = node_positions[backup["id"]]
                x1, y1 = node_positions[switch_id]
                fig.add_trace(go.Scatter(
                    x=[x0, x1], y=[y0, y1], mode='lines',
                    line=dict(color=health_colour_map.get(backup["health"], "gray"), width=3),
                    name=f"{backup['name']} → {switch_id}",
                    text=f"Port: {port}",
                    hoverinfo='text', showlegend=False))

    # Add all images to the layout
    fig.update_layout(images=images_to_add)

    cloud_name = data['private_cloud'].get('name', 'Private Cloud') if data['private_cloud'] else 'Private Cloud'
    fig.update_layout(
        title=f"{cloud_name} Architecture",
        # showlegend=True,
        # legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99, bgcolor="rgba(255, 255, 255, 0.8)", bordercolor="black", borderwidth=1),
        
        showlegend=False, 
        hovermode='closest',
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='white', paper_bgcolor='white', width=1000, height=800
    )
    pio.write_html(fig, file=output_path, auto_open=False)
    logger.info(f"Interactive topology saved to {output_path}")
    abs_path = os.path.abspath(output_path)
    logger.info(f"Attempting to open {abs_path} in web browser...")
    webbrowser.open_new_tab(f"file://{abs_path}")

# --- Monitor and Update Both Outputs ---
def update_all():
    data = fetch_data_from_supabase()
    if not data:
        logger.error("Could not fetch data from Supabase.")
        return
    generate_png_topology(data)
    generate_interactive_topology(data)

class DatabaseMonitor:
    def __init__(self, update_function, check_interval=30):
        self.update_function = update_function
        self.check_interval = check_interval
        self.last_check_time = None
        self.running = False
        self.thread = None
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Database monitoring started. Checking every {self.check_interval} seconds.")
    def _monitor_loop(self):
        while self.running:
            try:
                now = time.time()
                if self.last_check_time is None or (now - self.last_check_time) >= self.check_interval:
                    logger.info("Checking for database changes...")
                    self.last_check_time = now
                    self.update_function()
            except Exception as e:
                logger.error(f"Error monitoring database: {e}")
            time.sleep(1)
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("Database monitoring stopped.")

if __name__ == "__main__":
    logger.info("Generating initial topology (PNG + HTML)...")
    update_all()
    db_monitor = DatabaseMonitor(update_all, check_interval=10)
    db_monitor.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        db_monitor.stop()
        logger.info("Program terminated by user.")