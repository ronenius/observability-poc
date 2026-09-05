# OpenShift 4.16 Air-Gapped Observability Deployment Guide

This directory contains the adapted, production-grade Kubernetes/OpenShift manifests and microservices configured specifically for **Red Hat OpenShift 4.16** running in an **air-gapped (disconnected / offline)** network.

---

## Key OpenShift 4.16 Airgap Adaptations Made

1. **Native OpenShift Ingress (`Route`)**:
   - Replaced all `type: LoadBalancer` services with OpenShift `Route` resources (`route.openshift.io/v1`) using Edge TLS termination.
   - Routes provided for:
     - `frontend` in `observability-poc`
     - `holmesgpt-docs` in `holmes-docs` (or target namespace)
     - `grafana` in `monitoring`
2. **SecurityContextConstraints (SCC) Compatibility**:
   - OpenShift 4.16 enforces `restricted-v2` by default.
   - Declarative `ClusterRoleBinding` manifests are included:
     - [`k8s/monitoring/alloy/scc-binding.yaml`](k8s/monitoring/alloy/scc-binding.yaml) grants `system:openshift:scc:hostmount-anyuid` to Grafana Alloy.
     - [`k8s/monitoring/kube-prometheus-stack/node-exporter-scc.yaml`](k8s/monitoring/kube-prometheus-stack/node-exporter-scc.yaml) grants `system:openshift:scc:privileged` to Prometheus Node Exporter.
3. **CRI-O Runtime Adjustments**:
   - Removed legacy `/var/lib/docker/containers` mounts from Grafana Alloy. OpenShift uses CRI-O, which logs to `/var/log/pods`.
4. **Airgap Offline Telemetry & Web UI**:
   - Removed external webhook calls (`webhook.site`) from OpenTelemetry Collector and Grafana Alloy.
   - Removed Google Fonts CDN preconnect/stylesheets from `frontend/index.html`; using local system font stacks.
   - Auto-instrumentation init containers in [`k8s/instrumentation.yaml`](k8s/instrumentation.yaml) explicitly point to internal mirrored images instead of public `ghcr.io`.
5. **Storage Adaptation**:
   - Thanos object store secret example in [`k8s/monitoring/kube-prometheus-stack/thanos-objstore-secret.example.yaml`](k8s/monitoring/kube-prometheus-stack/thanos-objstore-secret.example.yaml) configured for on-prem S3 (Red Hat OpenShift Data Foundation / Ceph or MinIO).

---

## Deployment Playbook

### Step 1: Image Mirroring
In an air-gapped OpenShift environment, mirror all required images to your internal registry (e.g., OpenShift Integrated Registry, Harbor, or Quay) from a connected bastion host:

```bash
# Set your internal registry
INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"
TARGET_NS="observability-poc"

# Application images
oc image mirror docker.io/your-registry/frontend:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/frontend:latest
oc image mirror docker.io/your-registry/backend1:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/backend1:latest
oc image mirror docker.io/your-registry/backend2:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/backend2:latest

# OTel Operator and Auto-Instrumentation init containers
oc image mirror ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/autoinstrumentation-python:latest
oc image mirror ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/autoinstrumentation-java:latest
oc image mirror ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/autoinstrumentation-nodejs:latest
oc image mirror ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:latest ${INTERNAL_REGISTRY}/${TARGET_NS}/opentelemetry-collector-contrib:0.118.0
```

---

### Step 2: OpenShift Security Permissions (SCC)
Apply the SecurityContextConstraints bindings:

```bash
# Alloy hostPath mount permissions
oc apply -f k8s/monitoring/alloy/scc-binding.yaml

# Node exporter privileged permissions
oc apply -f k8s/monitoring/kube-prometheus-stack/node-exporter-scc.yaml
```

---

### Step 3: Deploy Monitoring Stack
Deploy Prometheus, Alertmanager, Grafana, Loki, Tempo, and Alloy:

```bash
# Kube Prometheus Stack
oc apply -f k8s/monitoring/kube-prometheus-stack/manifest.yaml

# Data sources & Dashboards
oc apply -f k8s/monitoring/kube-prometheus-stack/grafana-datasources-loki-tempo.yaml
oc apply -f k8s/monitoring/kube-prometheus-stack/dashboards/observability-poc-dashboard.yaml

# Grafana OpenShift Route
oc apply -f k8s/monitoring/kube-prometheus-stack/grafana-route.yaml

# Loki & Tempo
oc apply -f k8s/monitoring/loki/manifest.yaml
oc apply -f k8s/monitoring/tempo/manifest.yaml
oc apply -f k8s/monitoring/tempo/service-monitor.yaml

# Grafana Alloy
oc apply -f k8s/monitoring/alloy/alloy.yaml
```

---

### Step 4: Deploy Observability POC Applications
Create the namespace and deploy the microservices and OpenTelemetry collector:

```bash
oc new-project observability-poc

# OTel Collector & Instrumentation
oc apply -f k8s/instrumentation.yaml
oc apply -f k8s/otel-collector.yaml

# Applications
oc apply -f k8s/backend2.yaml
oc apply -f k8s/backend1.yaml
oc apply -f k8s/frontend.yaml
```

---

### Step 5: Deploy HolmesGPT Airgapped Docs (Optional)
```bash
oc apply -f holmes-docs/k8s.yaml
```

---

### Accessing the Web Consoles
Retrieve the generated OpenShift Route hostnames:

```bash
# Frontend UI
oc get route frontend -n observability-poc

# Grafana Dashboard
oc get route grafana -n monitoring

# HolmesGPT Docs
oc get route holmesgpt-docs
```
