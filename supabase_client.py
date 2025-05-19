import requests
import logging

logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = "https://xpchztgrhfhgtcekazan.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwY2h6dGdyaGZoZ3RjZWthemFuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDUxNTY3MTUsImV4cCI6MjA2MDczMjcxNX0.VUKKlhtXgZdr2G4U-CGOjHH6TgugrPyg0cFzePzC4Q8"

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
