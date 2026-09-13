#!/usr/bin/env python3
"""
Sync source files into Kubernetes ConfigMap manifests.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
K8S_DIR = os.path.join(BASE_DIR, "k8s")

def indent_content(text: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else "" for line in text.splitlines()) + "\n"

def sync_instance1_app():
    api_code = open(os.path.join(BASE_DIR, "instance1", "api.py")).read()
    forwarder_code = open(os.path.join(BASE_DIR, "instance1", "outbox_forwarder.py")).read()
    target_file = os.path.join(K8S_DIR, "03-instance1-app.yaml")
    
    with open(target_file) as f:
        content = f.read()

    # Find the deployment section separator (first '---')
    doc_parts = content.split("\n---\n", 1)
    if len(doc_parts) < 2:
        raise ValueError("Could not find '---' separator in 03-instance1-app.yaml")

    cm_header = """apiVersion: v1
kind: ConfigMap
metadata:
  name: instance1-scripts
  namespace: noc-platform
data:
  api.py: |
"""
    new_cm = cm_header + indent_content(api_code, 4) + "  outbox_forwarder.py: |\n" + indent_content(forwarder_code, 4)
    new_content = new_cm.rstrip() + "\n---\n" + doc_parts[1]
    with open(target_file, "w") as f:
        f.write(new_content)
    print(f"Updated {target_file}")

def sync_instance2_gateway():
    gw_code = open(os.path.join(BASE_DIR, "instance2", "gateway_and_ingestion.py")).read()
    target_file = os.path.join(K8S_DIR, "04-instance2-gateway.yaml")

    with open(target_file) as f:
        content = f.read()

    doc_parts = content.split("\n---\n", 1)
    if len(doc_parts) < 2:
        raise ValueError("Could not find '---' separator in 04-instance2-gateway.yaml")

    cm_header = """apiVersion: v1
kind: ConfigMap
metadata:
  name: instance2-scripts
  namespace: noc-platform
data:
  gateway_and_ingestion.py: |
"""
    new_cm = cm_header + indent_content(gw_code, 4)
    new_content = new_cm.rstrip() + "\n---\n" + doc_parts[1]
    with open(target_file, "w") as f:
        f.write(new_content)
    print(f"Updated {target_file}")

def sync_web_ui(target_filename: str, cm_name: str, port: int, title_suffix: str = ""):
    index_html = open(os.path.join(BASE_DIR, "web-ui", "index.html")).read()
    if title_suffix:
        index_html = index_html.replace(
            "<title>NOC Observability & Alert Console</title>",
            f"<title>NOC Alert Console - {title_suffix}</title>"
        )
    style_css = open(os.path.join(BASE_DIR, "web-ui", "style.css")).read()
    app_js = open(os.path.join(BASE_DIR, "web-ui", "app.js")).read()

    target_file = os.path.join(K8S_DIR, target_filename)
    with open(target_file) as f:
        content = f.read()

    doc_parts = content.split("\n---\n", 1)
    if len(doc_parts) < 2:
        raise ValueError(f"Could not find '---' separator in {target_filename}")

    proxy_target = "http://instance1-api:8081/api/;" if port == 8080 else "http://instance2-gateway:8082/api/;"

    nginx_conf = f"""server {{
    listen {port};
    server_name _;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    location / {{
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}

    location /api/ {{
        proxy_pass {proxy_target}
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
    }}

    location /healthz {{
        access_log off;
        return 200 "healthy\\n";
    }}
}}"""

    cm_content = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {cm_name}
  namespace: noc-platform
data:
  nginx.conf: |
{indent_content(nginx_conf, 4)}  index.html: |
{indent_content(index_html, 4)}  style.css: |
{indent_content(style_css, 4)}  app.js: |
{indent_content(app_js, 4)}"""

    new_content = cm_content.rstrip() + "\n---\n" + doc_parts[1]
    with open(target_file, "w") as f:
        f.write(new_content)
    print(f"Updated {target_file}")

if __name__ == "__main__":
    sync_instance1_app()
    sync_instance2_gateway()
    sync_web_ui("06-noc-web-ui.yaml", "noc-web-ui-assets", 8080)
    sync_web_ui("07-noc-web-ui-instance2.yaml", "noc-web-ui-instance2-assets", 8083, "Instance 2 (Secondary Replica)")
    print("All manifests successfully synchronized.")
