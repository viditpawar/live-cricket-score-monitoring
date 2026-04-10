import os
import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

API_KEY = os.getenv("CRICKET_API_KEY")
BASE_URL = "https://api.cricapi.com/v1/currentMatches"


def fetch_current_matches():
    response = requests.get(
        BASE_URL,
        params={
            "apikey": API_KEY,
            "offset": 0
        },
        timeout=10
    )
    response.raise_for_status()
    return response.json()


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


@app.route("/matches")
def matches():
    if not API_KEY:
        return jsonify({
            "error": "CRICKET_API_KEY not found in environment"
        }), 500

    try:
        data = fetch_current_matches()
        matches = data.get("data", [])

        simplified_matches = []

        for match in matches:
            simplified_matches.append({
                "id": match.get("id"),
                "name": match.get("name"),
                "match_type": match.get("matchType"),
                "status": match.get("status"),
                "venue": match.get("venue"),
                "date": match.get("date"),
                "teams": match.get("teams")
            })

        return jsonify({
            "total_matches": len(simplified_matches),
            "matches": simplified_matches
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Failed to fetch matches from cricket API",
            "details": str(e)
        }), 500
    except Exception as e:
        return jsonify({
            "error": "Unexpected error",
            "details": str(e)
        }), 500


@app.route("/live-score")
def live_score():
    if not API_KEY:
        return jsonify({
            "error": "CRICKET_API_KEY not found in environment"
        }), 500

    match_name = request.args.get("match_name")

    try:
        data = fetch_current_matches()
        matches = data.get("data", [])

        if not matches:
            return jsonify({
                "message": "No current matches found"
            })

        if match_name:
            selected_match = None

            for match in matches:
                name = match.get("name", "")
                if match_name.lower() in name.lower():
                    selected_match = match
                    break

            if not selected_match:
                return jsonify({
                    "message": f"No match found with name containing '{match_name}'"
                }), 404
        else:
            selected_match = matches[0]

        return jsonify({
            "id": selected_match.get("id"),
            "name": selected_match.get("name"),
            "match_type": selected_match.get("matchType"),
            "status": selected_match.get("status"),
            "venue": selected_match.get("venue"),
            "date": selected_match.get("date"),
            "teams": selected_match.get("teams"),
            "score": selected_match.get("score")
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