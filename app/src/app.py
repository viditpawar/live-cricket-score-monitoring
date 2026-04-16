import os
import time
import requests
from copy import deepcopy
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Histogram

load_dotenv()

app = Flask(__name__)
metrics = PrometheusMetrics(app, path="/metrics")

API_KEY = os.getenv("CRICKET_API_KEY")
CURRENT_MATCHES_URL = "https://api.cricapi.com/v1/currentMatches"
HOME_MATCHES_URL = "https://api.cricapi.com/v1/cricScore"
MATCHES_CACHE_TTL_SECONDS = int(os.getenv("MATCHES_CACHE_TTL_SECONDS", "300"))

# Cache for homepage match cards to reduce API hits.
home_matches_cache = {
    "timestamp": 0.0,
    "payload": None
}

# Custom Prometheus metrics
cricket_api_requests_total = Counter(
    "cricket_api_requests_total",
    "Total number of requests made to the cricket API"
)

cricket_api_failures_total = Counter(
    "cricket_api_failures_total",
    "Total number of failed cricket API requests"
)

cricket_api_response_time_seconds = Histogram(
    "cricket_api_response_time_seconds",
    "Response time of cricket API requests in seconds"
)

live_score_requests_total = Counter(
    "live_score_requests_total",
    "Total number of requests made to the /live-score endpoint"
)


def fetch_cricket_api(endpoint, extra_params=None):
    cricket_api_requests_total.inc()
    start_time = time.time()

    try:
        params = {
            "apikey": API_KEY
        }

        if extra_params:
            params.update(extra_params)

        response = requests.get(
            endpoint,
            params=params,
            timeout=10
        )
        response.raise_for_status()
        payload = response.json()

        status = str(payload.get("status", "")).lower()

        if status and status != "success":
            reason = payload.get("reason") or payload.get("message") or "Unknown cricket API error"
            return [], reason

        data = payload.get("data", [])
        if not isinstance(data, list):
            return [], None

        return data, None

    except requests.exceptions.RequestException:
        cricket_api_failures_total.inc()
        raise

    finally:
        duration = time.time() - start_time
        cricket_api_response_time_seconds.observe(duration)


def fetch_current_matches():
    return fetch_cricket_api(
        CURRENT_MATCHES_URL,
        {
            "offset": 0
        }
    )


def fetch_homepage_matches():
    return fetch_cricket_api(HOME_MATCHES_URL)


def first_non_none(*values):
    for value in values:
        if value is not None:
            return value

    return None


def stringify_score(score):
    if not score:
        return None

    if isinstance(score, str):
        return score

    if isinstance(score, list):
        parts = []

        for innings in score:
            if not isinstance(innings, dict):
                continue

            innings_name = innings.get("inning") or innings.get("name") or ""
            runs = first_non_none(innings.get("r"), innings.get("runs"))
            wickets = first_non_none(innings.get("w"), innings.get("wickets"))
            overs = first_non_none(innings.get("o"), innings.get("overs"))

            section = innings_name.strip()

            if runs is not None:
                score_line = str(runs)
                if wickets is not None:
                    score_line += f"/{wickets}"

                section = f"{section} {score_line}".strip()

            if overs is not None:
                section = f"{section} ({overs} ov)".strip()

            if section:
                parts.append(section)

        if parts:
            return " | ".join(parts)

    return str(score)


def extract_teams(match):
    teams = match.get("teams")

    if isinstance(teams, list):
        return teams

    t1 = match.get("t1")
    t2 = match.get("t2")
    if t1 and t2:
        return [t1, t2]

    team_info = match.get("teamInfo")
    if isinstance(team_info, list):
        parsed_names = []
        for team in team_info:
            if isinstance(team, dict):
                name = team.get("name")
                if name:
                    parsed_names.append(name)

        if parsed_names:
            return parsed_names

    return []


def simplify_match(match):
    return {
        "id": match.get("id") or match.get("unique_id"),
        "name": match.get("name") or match.get("matchName") or match.get("title"),
        "match_type": match.get("matchType") or match.get("type"),
        "status": match.get("status"),
        "venue": match.get("venue"),
        "date": match.get("date") or match.get("dateTimeGMT") or match.get("dateTime"),
        "teams": extract_teams(match),
        "score": stringify_score(match.get("score")),
        "state": str(match.get("ms") or "").lower() or None
    }


def dedupe_matches(matches):
    seen = set()
    deduped = []

    for match in matches:
        key = match.get("id")

        if not key:
            key = f"{match.get('name', '')}|{match.get('date', '')}"

        if key in seen:
            continue

        seen.add(key)
        deduped.append(match)

    return deduped


def parse_match_datetime(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return datetime.min.replace(tzinfo=timezone.utc)

    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value.replace("Z", "+00:00")

            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    return datetime.min.replace(tzinfo=timezone.utc)


def is_recent_result(match):
    state = (match.get("state") or "").lower()
    status = (match.get("status") or "").lower()

    if state in {"result", "completed"}:
        return True

    recent_status_tokens = (
        "won",
        "match ended",
        "result",
        "draw",
        "tied",
        "abandoned",
        "no result",
        "cancelled"
    )

    return any(token in status for token in recent_status_tokens)


def is_live_match(match):
    state = (match.get("state") or "").lower()
    status = (match.get("status") or "").lower()

    if state in {"live", "inprogress"}:
        return True

    live_status_tokens = (
        "live",
        "innings",
        "need",
        "required",
        "trail",
        "lead",
        "stumps",
        "day "
    )

    if any(token in status for token in live_status_tokens) and not is_recent_result(match):
        return True

    return False


def is_upcoming_match(match):
    state = (match.get("state") or "").lower()
    status = (match.get("status") or "").lower()

    if state in {"fixture", "upcoming"}:
        return True

    upcoming_status_tokens = (
        "starts",
        "scheduled",
        "yet to begin",
        "not started"
    )

    return any(token in status for token in upcoming_status_tokens)


def read_cached_home_payload():
    payload = home_matches_cache.get("payload")
    timestamp = home_matches_cache.get("timestamp", 0.0)

    if payload is None:
        return None, None

    age_seconds = int(time.time() - timestamp)
    return deepcopy(payload), age_seconds


def write_cached_home_payload(payload):
    home_matches_cache["payload"] = deepcopy(payload)
    home_matches_cache["timestamp"] = time.time()


@app.route("/")
def home():
    return render_template("index.html")


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

    force_refresh = request.args.get("refresh") == "1"
    cached_payload, cache_age_seconds = read_cached_home_payload()

    if cached_payload and not force_refresh and cache_age_seconds <= MATCHES_CACHE_TTL_SECONDS:
        cached_payload["served_from_cache"] = True
        cached_payload["cache_age_seconds"] = cache_age_seconds
        cached_payload["cache_ttl_seconds"] = MATCHES_CACHE_TTL_SECONDS
        return jsonify(cached_payload)

    try:
        raw_matches, warning = fetch_homepage_matches()

        if warning:
            if cached_payload:
                cached_payload["served_from_cache"] = True
                cached_payload["cache_age_seconds"] = cache_age_seconds
                cached_payload["cache_ttl_seconds"] = MATCHES_CACHE_TTL_SECONDS
                cached_payload["warning"] = f"Showing cached matches: {warning}"
                return jsonify(cached_payload)

            return jsonify({
                "error": "Failed to fetch matches from cricket API",
                "details": warning
            }), 503

        simplified_matches = [simplify_match(match) for match in raw_matches]
        simplified_matches = [
            match for match in simplified_matches
            if match.get("id") or match.get("name") or match.get("teams")
        ]
        simplified_matches = dedupe_matches(simplified_matches)

        live_matches = [match for match in simplified_matches if is_live_match(match)]
        recent_matches = [match for match in simplified_matches if is_recent_result(match)]
        upcoming_matches = [
            match for match in simplified_matches
            if is_upcoming_match(match) and not is_live_match(match) and not is_recent_result(match)
        ]

        live_matches.sort(key=lambda match: parse_match_datetime(match.get("date")), reverse=True)
        recent_matches.sort(key=lambda match: parse_match_datetime(match.get("date")), reverse=True)
        upcoming_matches.sort(key=lambda match: parse_match_datetime(match.get("date")))

        payload = {
            "total_matches": len(simplified_matches),
            "live_count": len(live_matches),
            "recent_count": len(recent_matches),
            "upcoming_count": len(upcoming_matches),
            "matches": simplified_matches,
            "live_matches": live_matches,
            "recent_matches": recent_matches,
            "upcoming_matches": upcoming_matches,
            "served_from_cache": False,
            "cache_ttl_seconds": MATCHES_CACHE_TTL_SECONDS,
            "warning": None
        }

        write_cached_home_payload(payload)
        payload["cache_age_seconds"] = 0

        return jsonify(payload)

    except requests.exceptions.RequestException as e:
        if cached_payload:
            cached_payload["served_from_cache"] = True
            cached_payload["cache_age_seconds"] = cache_age_seconds
            cached_payload["cache_ttl_seconds"] = MATCHES_CACHE_TTL_SECONDS
            cached_payload["warning"] = f"Showing cached matches: {str(e)}"
            return jsonify(cached_payload)

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
    live_score_requests_total.inc()

    if not API_KEY:
        return jsonify({
            "error": "CRICKET_API_KEY not found in environment"
        }), 500

    match_name = request.args.get("match_name")

    try:
        matches, warning = fetch_current_matches()

        if warning:
            return jsonify({
                "error": "Failed to fetch data from cricket API",
                "details": warning
            }), 503

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
    app.run(host="0.0.0.0", port=5000, debug=False)
