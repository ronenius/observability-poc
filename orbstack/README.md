# OrbStack Local Development Guide

This directory contains the standalone Kubernetes manifests and microservice code configured specifically for local development and testing on **macOS with OrbStack**.

---

## Architecture Characteristics for OrbStack

1. **Direct Host Routing (`type: LoadBalancer`)**:
   - OrbStack natively provisions dedicated LAN IPs for Kubernetes `LoadBalancer` services.
   - `frontend` service is exposed directly at `http://localhost:32293` or the allocated OrbStack IP.
   - `holmesgpt-docs` service is exposed directly on port `8080`.
2. **Local Image Evaluation (`imagePullPolicy: Never` / `IfNotPresent`)**:
   - Docker images built directly in OrbStack's Docker engine can be consumed instantly by Kubernetes without a remote registry push.
3. **Multi-Tenancy & Edge Telemetry**:
   - Includes local OpenTelemetry Collector, Grafana Alloy daemonset, Loki, Tempo, and Prometheus.

---

## Quickstart

### 1. Build Docker Images
```bash
# Applications
docker build -t your-registry/backend1:latest ./backend1
docker build -t your-registry/backend2:latest ./backend2
docker build -t your-registry/frontend:latest ./frontend

# HolmesGPT Web Chat GUI
docker build -t your-registry/holmes-ui:latest ./holmes-ui

# HolmesGPT Docs (Optional)
docker build -t your-registry/holmes-docs:latest ./holmes-docs
```

### 2. Deploy Observability Infrastructure
```bash
# Cert-Manager and OTel Operator
kubectl apply -f k8s/monitoring/opentelemetry-operator/cert-manager.yaml
kubectl apply -f k8s/monitoring/opentelemetry-operator/opentelemetry-operator.yaml

# Prometheus Stack, Loki, Tempo, Alloy
kubectl apply -f k8s/monitoring/kube-prometheus-stack/manifest.yaml
kubectl apply -f k8s/monitoring/kube-prometheus-stack/grafana-datasources-loki-tempo.yaml
kubectl apply -f k8s/monitoring/kube-prometheus-stack/dashboards/observability-poc-dashboard.yaml
kubectl apply -f k8s/monitoring/loki/manifest.yaml
kubectl apply -f k8s/monitoring/tempo/manifest.yaml
kubectl apply -f k8s/monitoring/tempo/service-monitor.yaml
kubectl apply -f k8s/monitoring/alloy/alloy.yaml
```

### 3. Deploy Observability POC Applications
```bash
kubectl apply -f k8s/instrumentation.yaml
kubectl apply -f k8s/otel-collector.yaml
kubectl apply -f k8s/backend2.yaml
kubectl apply -f k8s/backend1.yaml
kubectl apply -f k8s/frontend.yaml
```

### 4. Deploy HolmesGPT AI Agent & Docs
```bash
# Deploy HolmesGPT with all connected toolsets (Prometheus, Loki, Tempo, Grafana, Splunk, K8s)
kubectl apply -f k8s/holmes/holmes.yaml

# Set your LLM API Key (OpenAI, Gemini, or Claude) in the secret:
kubectl create secret generic holmes-secrets -n holmes \
  --from-literal=OPENAI_API_KEY="<your-api-key>" \
  --from-literal=GRAFANA_USER="admin" \
  --from-literal=GRAFANA_PASSWORD="9oCV8ish5xVlGx1Kl4K8kTn3CJIb34QGad2B6Dc3" \
  --from-literal=SPLUNK_USER="admin" \
  --from-literal=SPLUNK_PASSWORD="Admin@123456" \
  --dry-run=client -o yaml | kubectl apply -f -

# Deploy HolmesGPT Web Chat GUI
kubectl apply -f k8s/holmes/ui.yaml

# Deploy HolmesGPT Docs (Optional)
kubectl apply -f holmes-docs/k8s.yaml
```

### 5. Access Endpoints
- **Frontend Dashboard**: `kubectl get svc frontend -n observability-poc` (open the external IP / port in your browser)
- **Grafana**: `kubectl port-forward svc/prometheus-stack-grafana -n monitoring 3000:80` (open `http://localhost:3000`, user: `admin`)
- **Splunk Enterprise**: `http://localhost:8000` (user: `admin`, pass: `Admin@123456`)
- **HolmesGPT Chat GUI**: `http://localhost:5055` (Interactive AI SRE Chat Interface connected to all telemetry toolsets)
- **HolmesGPT API**: `http://localhost:5050` (`/healthz`, `/readyz`, `/api/info`, `/api/chat`)

