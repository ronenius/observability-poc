FROM python:3.10-slim

WORKDIR /app

# Copy application files
COPY index.html style.css app.js server.py /app/

# Environment defaults
ENV PORT=8080 \
    HOLMES_BACKEND_URL=http://holmes:5050 \
    STATIC_DIR=/app \
    PYTHONUNBUFFERED=1

# Run as non-root user (compatible with OpenShift restricted / restricted-v2 SCC)
USER 10001:10001

EXPOSE 8080

ENTRYPOINT ["python3", "/app/server.py"]
