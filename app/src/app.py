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
MATCH_INFO_URL = "https://api.cricapi.com/v1/match_info"
MATCHES_CACHE_TTL_SECONDS = int(os.getenv("MATCHES_CACHE_TTL_SECONDS", "300"))
MATCH_INFO_CACHE_TTL_SECONDS = int(os.getenv("MATCH_INFO_CACHE_TTL_SECONDS", "21600"))

# Cache for homepage match cards to reduce API hits.
home_matches_cache = {
    "timestamp": 0.0,
    "payload": None
}

# Cache for per-match detail lookups.
match_info_cache = {}

TIMEZONE_HINTS = (
    ("india", "Asia/Kolkata"),
    ("mumbai", "Asia/Kolkata"),
    ("delhi", "Asia/Kolkata"),
    ("chennai", "Asia/Kolkata"),
    ("kolkata", "Asia/Kolkata"),
    ("hyderabad", "Asia/Kolkata"),
    ("bengaluru", "Asia/Kolkata"),
    ("bangalore", "Asia/Kolkata"),
    ("ahmedabad", "Asia/Kolkata"),
    ("lucknow", "Asia/Kolkata"),
    ("jaipur", "Asia/Kolkata"),
    ("pakistan", "Asia/Karachi"),
    ("lahore", "Asia/Karachi"),
    ("karachi", "Asia/Karachi"),
    ("rawalpindi", "Asia/Karachi"),
    ("multan", "Asia/Karachi"),
    ("islamabad", "Asia/Karachi"),
    ("peshawar", "Asia/Karachi"),
    ("quetta", "Asia/Karachi"),
    ("sri lanka", "Asia/Colombo"),
    ("colombo", "Asia/Colombo"),
    ("galle", "Asia/Colombo"),
    ("kandy", "Asia/Colombo"),
    ("new zealand", "Pacific/Auckland"),
    ("auckland", "Pacific/Auckland"),
    ("wellington", "Pacific/Auckland"),
    ("christchurch", "Pacific/Auckland"),
    ("australia", "Australia/Sydney"),
    ("sydney", "Australia/Sydney"),
    ("melbourne", "Australia/Melbourne"),
    ("brisbane", "Australia/Brisbane"),
    ("perth", "Australia/Perth"),
    ("adelaide", "Australia/Adelaide"),
    ("hobart", "Australia/Hobart"),
    ("england", "Europe/London"),
    ("london", "Europe/London"),
    ("manchester", "Europe/London"),
    ("birmingham", "Europe/London"),
    ("south africa", "Africa/Johannesburg"),
    ("johannesburg", "Africa/Johannesburg"),
    ("cape town", "Africa/Johannesburg"),
    ("durban", "Africa/Johannesburg"),
    ("bangladesh", "Asia/Dhaka"),
    ("dhaka", "Asia/Dhaka"),
    ("chattogram", "Asia/Dhaka"),
    ("zimbabwe", "Africa/Harare"),
    ("harare", "Africa/Harare"),
    ("bulawayo", "Africa/Harare"),
    ("namibia", "Africa/Windhoek"),
    ("windhoek", "Africa/Windhoek"),
    ("united states", "America/New_York"),
    ("usa", "America/New_York"),
    ("canada", "America/Toronto"),
    ("west indies", "America/Jamaica"),
    ("jamaica", "America/Jamaica"),
    ("barbados", "America/Barbados"),
    ("trinidad", "America/Port_of_Spain"),
    ("afghanistan", "Asia/Kabul"),
    ("nepal", "Asia/Kathmandu"),
    ("uae", "Asia/Dubai"),
    ("dubai", "Asia/Dubai"),
    ("abu dhabi", "Asia/Dubai"),
    ("ireland", "Europe/Dublin"),
    ("dublin", "Europe/Dublin"),
    ("scotland", "Europe/London"),
    ("netherlands", "Europe/Amsterdam"),
    ("amsterdam", "Europe/Amsterdam")
)

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


def fetch_cricket_api(endpoint, extra_params=None, expect_list=True):
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

        data = payload.get("data")

        if expect_list:
            if not isinstance(data, list):
                return [], None
        else:
            if data is None:
                return None, None

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


def fetch_match_info(match_id):
    return fetch_cricket_api(
        MATCH_INFO_URL,
        {
            "id": match_id
        },
        expect_list=False
    )


def first_non_none(*values):
    for value in values:
        if value is not None:
            return value

    return None


def clean_text(value):
    if not isinstance(value, str):
        return None

    trimmed = value.strip()
    if not trimmed:
        return None

    return trimmed


def split_team_name(raw_name):
    normalized = clean_text(raw_name)
    if not normalized:
        return None, None

    short_name = None
    if "[" in normalized and "]" in normalized and normalized.rfind("[") < normalized.rfind("]"):
        start = normalized.rfind("[")
        end = normalized.rfind("]")
        short_candidate = normalized[start + 1:end].strip()
        if short_candidate:
            short_name = short_candidate

        name_candidate = normalized[:start].strip()
        if name_candidate:
            normalized = name_candidate

    return normalized, short_name


def sanitize_team_details(team_details):
    normalized = []
    seen = set()

    for team in team_details:
        if not isinstance(team, dict):
            continue

        name = team.get("name")
        short_name = team.get("short_name")
        logo = team.get("logo")

        if isinstance(name, str):
            name = name.strip()
        if isinstance(short_name, str):
            short_name = short_name.strip()
        if isinstance(logo, str):
            logo = logo.strip()

        if not name and not short_name and not logo:
            continue

        dedupe_key = (name or short_name or "").lower()
        if dedupe_key and dedupe_key in seen:
            continue

        if dedupe_key:
            seen.add(dedupe_key)

        normalized.append({
            "name": name,
            "short_name": short_name,
            "logo": logo
        })

    return normalized


def extract_team_details(match):
    team_details = []
    team_info = match.get("teamInfo")

    if isinstance(team_info, list):
        for team in team_info:
            if not isinstance(team, dict):
                continue

            team_details.append({
                "name": clean_text(team.get("name")) or clean_text(team.get("fullName")),
                "short_name": clean_text(team.get("shortname")) or clean_text(team.get("shortName")),
                "logo": team.get("img") or team.get("image")
            })

    if not team_details:
        for name_key, image_key in (("t1", "t1img"), ("t2", "t2img")):
            team_name, short_name = split_team_name(match.get(name_key))
            if not team_name and not short_name:
                continue

            team_details.append({
                "name": team_name,
                "short_name": short_name,
                "logo": match.get(image_key)
            })

    if not team_details:
        teams = match.get("teams")
        if isinstance(teams, list):
            for team_name in teams:
                normalized_name, normalized_short = split_team_name(team_name)
                team_details.append({
                    "name": normalized_name or clean_text(team_name),
                    "short_name": normalized_short,
                    "logo": None
                })

    return sanitize_team_details(team_details)


def format_innings_score(innings):
    if not isinstance(innings, dict):
        return None

    innings_name = clean_text(
        innings.get("inning")
        or innings.get("name")
        or innings.get("team")
    )
    runs = first_non_none(innings.get("r"), innings.get("runs"))
    wickets = first_non_none(innings.get("w"), innings.get("wickets"))
    overs = first_non_none(innings.get("o"), innings.get("overs"))

    section = innings_name or ""

    if runs is not None and str(runs).strip():
        score_line = str(runs).strip()
        if wickets is not None and str(wickets).strip():
            score_line += f"/{str(wickets).strip()}"

        section = f"{section} {score_line}".strip()

    if overs is not None and str(overs).strip():
        section = f"{section} ({str(overs).strip()} ov)".strip()

    return clean_text(section)


def score_lines_from_team_totals(match, team_details):
    t1_score = clean_text(match.get("t1s"))
    t2_score = clean_text(match.get("t2s"))

    if not t1_score and not t2_score:
        return []

    lines = []
    team_one = team_details[0] if len(team_details) > 0 else {}
    team_two = team_details[1] if len(team_details) > 1 else {}

    team_one_name = clean_text(team_one.get("short_name")) or clean_text(team_one.get("name")) or "Team 1"
    team_two_name = clean_text(team_two.get("short_name")) or clean_text(team_two.get("name")) or "Team 2"

    if t1_score:
        lines.append(f"{team_one_name}: {t1_score}")

    if t2_score:
        lines.append(f"{team_two_name}: {t2_score}")

    return lines


def extract_score_lines(match, team_details):
    raw_score = match.get("score")

    if isinstance(raw_score, str):
        cleaned = clean_text(raw_score)
        if cleaned:
            return [cleaned]

    if isinstance(raw_score, list):
        innings_lines = []
        for innings in raw_score:
            line = format_innings_score(innings)
            if line:
                innings_lines.append(line)

        if innings_lines:
            return innings_lines

    if isinstance(raw_score, dict):
        line = format_innings_score(raw_score)
        if line:
            return [line]

    return score_lines_from_team_totals(match, team_details)


def stringify_score(score_lines):
    if not score_lines:
        return None

    return " | ".join(score_lines)


def extract_match_name(match):
    direct_name = clean_text(match.get("name")) or clean_text(match.get("matchName")) or clean_text(match.get("title"))
    if direct_name:
        return direct_name

    team_one_name, _ = split_team_name(match.get("t1"))
    team_two_name, _ = split_team_name(match.get("t2"))

    if team_one_name and team_two_name:
        return f"{team_one_name} vs {team_two_name}"

    return None


def extract_match_state(match):
    state = clean_text(str(match.get("ms") or ""))
    if state:
        return state.lower()

    if match.get("matchEnded") is True:
        return "completed"

    if match.get("matchStarted") is True:
        return "live"

    return None


def extract_series_name(match):
    series = match.get("series")
    if isinstance(series, dict):
        return clean_text(series.get("name") or series.get("seriesName") or series.get("title"))

    return clean_text(series)


def extract_venue(match):
    direct_keys = ("venue", "ground", "location", "stadium")
    for key in direct_keys:
        value = clean_text(match.get(key))
        if value:
            return value

    venue_info = match.get("venueInfo")
    if isinstance(venue_info, dict):
        for key in ("venue", "name", "ground", "stadium"):
            value = clean_text(venue_info.get(key))
            if value:
                return value

        city = clean_text(venue_info.get("city"))
        country = clean_text(venue_info.get("country"))
        if city and country:
            return f"{city}, {country}"
        if city:
            return city

    return None


def normalize_match_date(match):
    for key in ("dateTimeGMT", "dateTime", "date"):
        raw_value = match.get(key)
        parsed = parse_match_datetime(raw_value)
        if parsed != datetime.min.replace(tzinfo=timezone.utc):
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return None


def infer_match_timezone(match, venue, series_name):
    source_parts = [
        venue,
        series_name,
        match.get("name"),
        match.get("t1"),
        match.get("t2")
    ]
    source_text = " ".join([part for part in source_parts if isinstance(part, str)]).lower()

    for hint, timezone_name in TIMEZONE_HINTS:
        if hint in source_text:
            return timezone_name

    return "UTC"


def extract_teams(match):
    team_details = extract_team_details(match)
    team_names = [team.get("name") for team in team_details if team.get("name")]
    return team_names


def simplify_match(match):
    team_details = extract_team_details(match)
    score_lines = extract_score_lines(match, team_details)
    venue = extract_venue(match)
    series_name = extract_series_name(match)

    return {
        "id": match.get("id") or match.get("unique_id"),
        "name": extract_match_name(match),
        "match_type": clean_text(match.get("matchType")) or clean_text(match.get("type")),
        "status": clean_text(match.get("status")),
        "venue": venue,
        "venue_timezone": infer_match_timezone(match, venue, series_name),
        "date": normalize_match_date(match),
        "teams": extract_teams(match),
        "team_details": team_details,
        "score": stringify_score(score_lines),
        "score_lines": score_lines,
        "state": extract_match_state(match),
        "series": series_name
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


def read_cached_match_info(match_id):
    cached = match_info_cache.get(match_id)
    if not cached:
        return None

    age_seconds = int(time.time() - cached.get("timestamp", 0.0))
    if age_seconds > MATCH_INFO_CACHE_TTL_SECONDS:
        match_info_cache.pop(match_id, None)
        return None

    return deepcopy(cached.get("payload"))


def write_cached_match_info(match_id, payload):
    match_info_cache[match_id] = {
        "timestamp": time.time(),
        "payload": deepcopy(payload)
    }


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


@app.route("/match-details/<match_id>")
def match_details(match_id):
    if not API_KEY:
        return jsonify({
            "error": "CRICKET_API_KEY not found in environment"
        }), 500

    if not match_id:
        return jsonify({
            "error": "Match id is required"
        }), 400

    cached_payload = read_cached_match_info(match_id)
    if cached_payload:
        return jsonify({
            "match": cached_payload,
            "served_from_cache": True
        })

    try:
        match_data, warning = fetch_match_info(match_id)

        if warning:
            return jsonify({
                "error": "Failed to fetch match details from cricket API",
                "details": warning
            }), 503

        if not isinstance(match_data, dict):
            return jsonify({
                "error": "Match details are unavailable for this id"
            }), 404

        simplified = simplify_match(match_data)
        if not simplified.get("id"):
            simplified["id"] = match_id

        write_cached_match_info(match_id, simplified)

        return jsonify({
            "match": simplified,
            "served_from_cache": False
        })
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Failed to fetch match details from cricket API",
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
