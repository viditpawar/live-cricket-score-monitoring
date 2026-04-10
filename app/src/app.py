from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "message": "Live Cricket Score Monitoring API is running"
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    })

@app.route("/live-score")
def live_score():
    return jsonify({
        "match_name": "India vs Australia",
        "status": "Live",
        "score": "145/3",
        "overs": "17.2",
        "batting_team": "India",
        "bowling_team": "Australia",
        "current_run_rate": 8.36
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)