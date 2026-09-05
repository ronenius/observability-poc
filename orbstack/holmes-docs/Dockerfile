# Stage 1: Build documentation
FROM python:3.11-slim AS builder

WORKDIR /app

# Ensure Python includes the repo root in module search path
ENV PYTHONPATH="/app"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    pip install --no-cache-dir poetry && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/HolmesGPT/holmesgpt.git .

# Prevent external font requests across air-gapped boundaries (properly replace existing font block)
RUN python3 -c "import re; p='mkdocs.yml'; s=open(p).read(); s=re.sub(r'font:\s*\n\s*text:[^\n]+\n\s*code:[^\n]+', 'font: false', s); open(p,'w').write(s)"

# Localize external CNCF logo so it displays offline in airgap
RUN mkdir -p docs/assets && \
    curl -sSL -o docs/assets/cncf-color-bg.svg https://www.cncf.io/wp-content/uploads/2022/07/cncf-color-bg.svg || true && \
    sed -i 's|https://www.cncf.io/wp-content/uploads/2022/07/cncf-color-bg.svg|assets/cncf-color-bg.svg|g' docs/index.md

RUN poetry config virtualenvs.create false && \
    poetry install --no-root --with=dev && \
    mkdocs build

# Stage 2: Serve via unprivileged Nginx
FROM nginxinc/nginx-unprivileged:alpine
COPY --from=builder /app/site /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]