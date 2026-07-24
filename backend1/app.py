import logging
import random

import requests
from flask import Flask, Response, jsonify
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

# Standard Python logging - OTel will dynamically inject the trace variables
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger("backend1")

app = Flask(__name__)

# Prometheus Metric Definition
REQUEST_COUNTER = Counter('app_requests_total', 'Total number of requests received')

@app.route('/metrics')
def metrics():
    """Exposes the Prometheus metrics endpoint"""
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route('/api/process')
def trigger_backend2():
    # Increment the counter on request
    REQUEST_COUNTER.inc()
    logger.info("Backend 1 (Python) received request from Frontend.")
    
    # 10% chance to drop the request and return an error
    if random.random() < 0.10:
        logger.error("Simulated failure: Randomly dropping request (10% chance).")
        return jsonify({"error": "Simulated failure in Backend 1"}), 500

    logger.info("Forwarding to Backend 2...")
    
    try:
        # The OTel agent automatically injects trace headers into this outbound request
        response = requests.get('http://backend2.observability-poc.svc.cluster.local:8080/api/data')
        response.raise_for_status()
        
        logger.info("Successfully received response from Backend 2")
        return jsonify({
            "status": "success",
            "backend2_data": response.json()
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to communicate with Backend 2: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)