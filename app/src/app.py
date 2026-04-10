from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)

# expose metrics at /metrics
metrics = PrometheusMetrics(app, path="/metrics")

@app.route("/")
def home():
    return jsonify({"message": "API is running"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)