import logging

import requests
from flask import Flask, jsonify

# Standard Python logging - OTel will dynamically inject the trace variables
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger("backend1")

app = Flask(__name__)

@app.route('/api/trigger') # Adjust if your frontend calls a different route
def trigger_backend2():
    logger.info("Backend 1 (Python) received request from Frontend. Forwarding to Backend 2...")
    
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