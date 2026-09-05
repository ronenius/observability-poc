# Observability Stack Kubernetes Manifests

This directory contains the exact Kubernetes manifests and Helm configurations deployed in the `monitoring` and `opentelemetry-operator-system` namespaces of your cluster.

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │    Workload Pods (observability-poc)   │
                      │  Node.js • Python Flask • Java Spring  │
                      └───────┬───────────────┬────────────────┘
                              │ OTLP Traces   │ Container Logs
                              │ & Metrics     │
                              ▼               ▼
┌───────────────────────────────────────┐   ┌───────────────────────────┐
│ OpenTelemetry Collector (local-edge)  │   │   Grafana Alloy DaemonSet │
│ (OpenTelemetry Operator Managed)      │   │   (Log Shipper)           │
└──────────┬───────────┬─────────────┬──┘   └─────────────┬─────────────┘
           │ Metrics   │ Traces      │ Logs               │ Pod Logs
           ▼           ▼             ▼                    ▼
┌──────────────────┐ ┌───────────┐ ┌────────────────────────────────────┐
│ Prometheus Stack │ │   Tempo   │ │             Loki                   │
│ (Remote Write    │ │  (Tracing │ │ (SingleBinary + Gateway Ingestion) │
│  + Exemplars)    │ │   Port    │ │                                    │
│                  │ │   4317)   │ │                                    │
└──────────────────┘ └───────────┘ └────────────────────────────────────┘
```

---

## Directory Structure

```
k8s/monitoring/
├── README.md
├── cert-manager/ (under opentelemetry-operator)
│   └── cert-manager.yaml             # v1.13.0 cert-manager prerequisite for webhooks
├── opentelemetry-operator/
│   ├── cert-manager.yaml             # cert-manager v1.13.0
│   └── opentelemetry-operator.yaml   # v0.156.0 OpenTelemetry Operator & CRDs
├── kube-prometheus-stack/
│   ├── values.yaml                   # Exact Helm values (exemplars, remote write, Thanos)
│   ├── manifest.yaml                 # Rendered Kubernetes manifests (Prometheus, Grafana, Alertmanager)
│   ├── thanos-objstore-secret.example.yaml # Template for Thanos object storage secret
│   ├── grafana-datasources-loki-tempo.yaml # Auto-provisioning for Loki & Tempo datasources
│   └── dashboards/
│       └── observability-poc-dashboard.yaml # Auto-provisioned Grafana dashboard for the POC
├── loki/
│   ├── values.yaml                   # Exact Helm values (SingleBinary, filesystem storage)
│   └── manifest.yaml                 # Rendered Kubernetes manifests (Loki, Gateway, Caches)
├── tempo/
│   ├── values.yaml                   # Exact Helm values (local backend, multi-tenancy)
│   ├── manifest.yaml                 # Rendered Kubernetes manifests (Tempo StatefulSet & Services)
│   └── service-monitor.yaml          # ServiceMonitor for Prometheus scraping Tempo metrics
└── alloy/
    └── alloy.yaml                    # Grafana Alloy DaemonSet for Kubernetes log collection
```

---

## Component Details & Deployment Instructions

### 1. Cert-Manager & OpenTelemetry Operator
- **Namespace**: `cert-manager` & `opentelemetry-operator-system`
- **Operator Version**: `v0.156.0` (image: `ghcr.io/open-telemetry/opentelemetry-operator/opentelemetry-operator:0.156.0`)
- **Cert-Manager Version**: `v1.13.0`

**Deploy via Manifests**:
```bash
# 1. Deploy cert-manager (required for operator admission webhooks)
kubectl apply -f k8s/monitoring/opentelemetry-operator/cert-manager.yaml

# 2. Deploy OpenTelemetry Operator & CRDs
kubectl apply -f k8s/monitoring/opentelemetry-operator/opentelemetry-operator.yaml
```

---

### 2. Kube-Prometheus-Stack
- **Namespace**: `monitoring`
- **Release Name**: `prometheus-stack`
- **Chart**: `prometheus-community/kube-prometheus-stack` (version: `82.9.0`)
- **Key Capabilities Enabled**:
  - `enableRemoteWriteReceiver: true` (receives OTLP metrics from OpenTelemetry Collector)
  - `enableFeatures: [exemplar-storage]` with `maxSize: 100000` (links metrics to distributed traces)
  - `thanosService: enabled` and Thanos sidecar configured for long-term storage retention

**Deploy via Helm**:
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Optional: Create Thanos secret before installing if using Thanos GCS/S3 storage
kubectl apply -f k8s/monitoring/kube-prometheus-stack/thanos-objstore-secret.example.yaml

helm upgrade --install prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 82.9.0 \
  --namespace monitoring \
  --create-namespace \
  -f k8s/monitoring/kube-prometheus-stack/values.yaml
```

**Deploy via Raw Manifest**:
```bash
kubectl apply -f k8s/monitoring/kube-prometheus-stack/manifest.yaml
```

---

### 3. Grafana Loki
- **Namespace**: `monitoring`
- **Release Name**: `loki`
- **Chart**: `grafana/loki` (version: `7.1.0`, app: `3.6.8`)
- **Key Capabilities Enabled**:
  - `deploymentMode: SingleBinary` (lightweight resource profile for local/dev clusters)
  - `auth_enabled: false` (open internal ingestion)
  - `storage.type: filesystem` (local PV-backed storage)
  - Direct OTLP log ingestion endpoint enabled (`http://loki.monitoring.svc.cluster.local:3100/otlp`)

**Deploy via Helm**:
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm upgrade --install loki grafana/loki \
  --version 7.1.0 \
  --namespace monitoring \
  --create-namespace \
  -f k8s/monitoring/loki/values.yaml
```

**Deploy via Raw Manifest**:
```bash
kubectl apply -f k8s/monitoring/loki/manifest.yaml
```

---

### 4. Grafana Tempo
- **Namespace**: `monitoring`
- **Release Name**: `tempo`
- **Chart**: `grafana/tempo` (version: `1.24.4`, app: `2.9.0`)
- **Key Capabilities Enabled**:
  - `storage.trace.backend: local` with 2Gi persistence
  - `tempo.multitenancyEnabled: true` (correlated with `headers_setter` in OTel Collector)
  - OTLP receiver listening on gRPC port 4317 (`tempo.monitoring.svc.cluster.local:4317`)
  - Prometheus metrics exposed on port 3200 (`tempo-prom-metrics`)

**Deploy via Helm**:
```bash
helm upgrade --install tempo grafana/tempo \
  --version 1.24.4 \
  --namespace monitoring \
  --create-namespace \
  -f k8s/monitoring/tempo/values.yaml
```

**Deploy via Raw Manifest**:
```bash
kubectl apply -f k8s/monitoring/tempo/manifest.yaml
```

**Deploy Tempo ServiceMonitor**:
```bash
kubectl apply -f k8s/monitoring/tempo/service-monitor.yaml
```

---

### 5. Grafana Alloy (Log Shipper DaemonSet)
- **Namespace**: `monitoring`
- **Role**: Automatically discovers pods across nodes, extracts Kubernetes metadata labels (pod, namespace, container), and streams logs to Loki Gateway (`http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push`).

**Deploy via Manifest**:
```bash
kubectl apply -f k8s/monitoring/alloy/alloy.yaml
```

---

### 6. Grafana Unified Datasources (Loki & Tempo)
- **Namespace**: `monitoring`
- **ConfigMap**: `k8s/monitoring/kube-prometheus-stack/grafana-datasources-loki-tempo.yaml`
- **Role**: Auto-provisions **Loki** and **Tempo** in Grafana via the `grafana_datasource: "1"` sidecar, enabling:
  - **Derived Fields**: Clicking a trace ID in a Loki log opens the trace waterfall in Tempo.
  - **Traces-to-Logs**: Clicking a span in Tempo opens the matching container logs in Loki.
  - **Traces-to-Metrics**: Correlating trace spans to Prometheus throughput.

**Deploy via Manifest**:
```bash
kubectl apply -f k8s/monitoring/kube-prometheus-stack/grafana-datasources-loki-tempo.yaml
```

---

### 7. Observability POC Grafana Dashboard
- **Namespace**: `monitoring`
- **ConfigMap**: `k8s/monitoring/kube-prometheus-stack/dashboards/observability-poc-dashboard.yaml`
- **Role**: Auto-provisions a comprehensive Grafana dashboard via the `grafana_dashboard: "1"` sidecar:
  - Total Invocations & Request Rate stats
  - Throughput by Pod timeseries
  - Live container logs streamed from Loki with trace ID links

**Deploy via Manifest**:
```bash
kubectl apply -f k8s/monitoring/kube-prometheus-stack/dashboards/observability-poc-dashboard.yaml
```

---

## Accessing the Observability Stack

### Accessing Grafana
Port-forward Grafana to your local machine:
```bash
kubectl port-forward svc/prometheus-stack-grafana -n monitoring 3000:80
```
- **URL**: [http://localhost:3000](http://localhost:3000)
- **Default Username**: `admin`
- **Get Password**:
  ```bash
  kubectl get secret -n monitoring prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 --decode; echo ""
  ```
- **Pre-installed Dashboard**: Navigate to **Dashboards** > **Observability POC • Telemetry & Distributed Traces**.
