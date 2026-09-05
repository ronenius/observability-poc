# Stage 1: Build documentation
FROM python:3.11-slim AS builder

WORKDIR /app

# Ensure Python includes the repo root in module search path
ENV PYTHONPATH="/app"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    pip install --no-cache-dir poetry && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/HolmesGPT/holmesgpt.git .

# Prevent external font requests across air-gapped boundaries
RUN sed -i '/theme:/a \    font: false' mkdocs.yml

RUN poetry config virtualenvs.create false && \
    poetry install --no-root --with=dev && \
    mkdocs build

# Stage 2: Serve via unprivileged Nginx
FROM nginxinc/nginx-unprivileged:alpine
COPY --from=builder /app/site /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]