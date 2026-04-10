import os
import requests
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

API_KEY = os.getenv("CRICKET_API_KEY")
BASE_URL = "https://api.cricapi.com/v1/currentMatches"


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


@app.route("/config-check")
def config_check():
    if API_KEY:
        return jsonify({
            "api_key_loaded": True,
            "message": "API key loaded successfully"
        })

    return jsonify({
        "api_key_loaded": False,
        "message": "API key not found"
    }), 500


@app.route("/live-score")
def live_score():
    if not API_KEY:
        return jsonify({
            "error": "CRICKET_API_KEY not found in environment"
        }), 500

    try:
        response = requests.get(
            BASE_URL,
            params={
                "apikey": API_KEY,
                "offset": 0
            },
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        matches = data.get("data", [])

        if not matches:
            return jsonify({
                "message": "No current matches found",
                "api_response": data
            })

        first_match = matches[0]

        return jsonify({
            "name": first_match.get("name"),
            "match_type": first_match.get("matchType"),
            "status": first_match.get("status"),
            "venue": first_match.get("venue"),
            "date": first_match.get("date"),
            "teams": first_match.get("teams"),
            "score": first_match.get("score")
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Failed to fetch data from cricket API",
            "details": str(e)
        }), 500
    except Exception as e:
        return jsonify({
            "error": "Unexpected error",
            "details": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)