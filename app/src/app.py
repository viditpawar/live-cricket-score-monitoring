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
MATCH_SCORECARD_URL = "https://api.cricapi.com/v1/match_scorecard"
MATCHES_CACHE_TTL_SECONDS = int(os.getenv("MATCHES_CACHE_TTL_SECONDS", "300"))
MATCH_INFO_CACHE_TTL_SECONDS = int(os.getenv("MATCH_INFO_CACHE_TTL_SECONDS", "21600"))
MATCH_INFO_LIVE_CACHE_TTL_SECONDS = int(os.getenv("MATCH_INFO_LIVE_CACHE_TTL_SECONDS", "90"))

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


def fetch_match_scorecard(match_id):
    return fetch_cricket_api(
        MATCH_SCORECARD_URL,
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


def has_meaningful_value(value):
    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0

    return True


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


def stringify_value(value):
    if value is None:
        return None

    if isinstance(value, str):
        return clean_text(value)

    if isinstance(value, (int, float)):
        return str(value)

    return None


def build_score_fragment(runs, wickets, overs):
    runs_text = stringify_value(runs)
    wickets_text = stringify_value(wickets)
    overs_text = stringify_value(overs)

    section = ""
    if runs_text:
        section = runs_text
        if wickets_text:
            section += f"/{wickets_text}"

    if overs_text:
        if section:
            section = f"{section} ({overs_text} ov)"
        else:
            section = f"{overs_text} ov"

    return clean_text(section)


def normalize_team_total_value(value):
    direct = stringify_value(value)
    if direct:
        return direct

    if isinstance(value, dict):
        return build_score_fragment(
            first_non_none(value.get("r"), value.get("runs"), value.get("total")),
            first_non_none(value.get("w"), value.get("wickets")),
            first_non_none(value.get("o"), value.get("overs"))
        )

    if isinstance(value, list):
        pieces = []
        for item in value:
            line = format_innings_score(item)
            if line:
                pieces.append(line)

        if pieces:
            return " | ".join(pieces)

    return None


def format_innings_score(innings):
    direct_text = stringify_value(innings)
    if direct_text:
        return direct_text

    if not isinstance(innings, dict):
        return None

    innings_name = clean_text(
        innings.get("inning")
        or innings.get("name")
        or innings.get("team")
    )
    score_blob = clean_text(
        innings.get("score")
        or innings.get("total")
        or innings.get("summary")
    )
    score_line = build_score_fragment(
        first_non_none(innings.get("r"), innings.get("runs")),
        first_non_none(innings.get("w"), innings.get("wickets")),
        first_non_none(innings.get("o"), innings.get("overs"))
    )

    if not score_line and score_blob:
        score_line = score_blob

    section = innings_name or ""
    if score_line:
        section = f"{section} {score_line}".strip()

    return clean_text(section)


def score_lines_from_score_map(raw_score):
    if not isinstance(raw_score, dict):
        return []

    standard_keys = {
        "inning", "name", "team", "score", "summary", "total",
        "r", "runs", "w", "wickets", "o", "overs"
    }

    if set(raw_score.keys()).issubset(standard_keys):
        return []

    lines = []
    for key, value in raw_score.items():
        key_name = clean_text(str(key))
        score_line = format_innings_score(value) or normalize_team_total_value(value)
        if not score_line:
            continue

        if key_name and not score_line.lower().startswith(key_name.lower()):
            lines.append(f"{key_name}: {score_line}")
        else:
            lines.append(score_line)

    return lines


def score_lines_from_team_totals(match, team_details):
    t1_score = normalize_team_total_value(match.get("t1s"))
    t2_score = normalize_team_total_value(match.get("t2s"))

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

        mapped_lines = score_lines_from_score_map(raw_score)
        if mapped_lines:
            return mapped_lines

    if raw_score is not None:
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


def merge_match_summaries(home_match, current_match):
    merged = deepcopy(home_match)

    if has_meaningful_value(current_match.get("status")):
        merged["status"] = current_match.get("status")

    for field in ("name", "match_type", "venue", "venue_timezone", "date", "series", "state"):
        if not has_meaningful_value(merged.get(field)) and has_meaningful_value(current_match.get(field)):
            merged[field] = current_match.get(field)

    if not has_meaningful_value(merged.get("teams")) and has_meaningful_value(current_match.get("teams")):
        merged["teams"] = deepcopy(current_match.get("teams"))

    if not has_meaningful_value(merged.get("team_details")) and has_meaningful_value(current_match.get("team_details")):
        merged["team_details"] = deepcopy(current_match.get("team_details"))

    current_score_lines = current_match.get("score_lines") or []
    if current_score_lines:
        merged["score_lines"] = current_score_lines
        merged["score"] = stringify_score(current_score_lines)
    elif not has_meaningful_value(merged.get("score")) and has_meaningful_value(current_match.get("score")):
        merged["score"] = current_match.get("score")

    return merged


def enrich_matches_with_current_feed(matches):
    try:
        current_matches_raw, warning = fetch_current_matches()
    except requests.exceptions.RequestException:
        return matches, "Live score enrichment is temporarily unavailable."

    if warning:
        return matches, f"Live score enrichment unavailable: {warning}"

    if not isinstance(current_matches_raw, list):
        return matches, None

    current_by_id = {}
    for raw_match in current_matches_raw:
        if not isinstance(raw_match, dict):
            continue

        simplified = simplify_match(raw_match)
        match_id = simplified.get("id")
        if not match_id:
            continue

        current_by_id[match_id] = simplified

    enriched = []
    for match in matches:
        match_id = match.get("id")
        current_match = current_by_id.get(match_id)
        if current_match:
            enriched.append(merge_match_summaries(match, current_match))
        else:
            enriched.append(match)

    return enriched, None


def extract_person_name(value):
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("fullName") or value.get("shortName"))

    return clean_text(value)


def normalize_inning_name(value):
    cleaned = clean_text(value)
    if not cleaned:
        return None

    return " ".join(cleaned.lower().replace("innings", "inning").split())


def build_score_summary_lookup(score_data):
    lookup = {}
    ordered = []

    if not isinstance(score_data, list):
        return lookup, ordered

    for score_entry in score_data:
        if not isinstance(score_entry, dict):
            continue

        summary = {
            "inning": clean_text(
                score_entry.get("inning")
                or score_entry.get("name")
                or score_entry.get("team")
            ),
            "runs": first_non_none(score_entry.get("r"), score_entry.get("runs")),
            "wickets": first_non_none(score_entry.get("w"), score_entry.get("wickets")),
            "overs": first_non_none(score_entry.get("o"), score_entry.get("overs"))
        }
        ordered.append(summary)

        summary_key = normalize_inning_name(summary.get("inning"))
        if summary_key:
            lookup[summary_key] = summary

    return lookup, ordered


def normalize_batting_rows(entries):
    if not isinstance(entries, list):
        return []

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        row = {
            "player": extract_person_name(
                first_non_none(
                    entry.get("batsman"),
                    entry.get("batter"),
                    entry.get("player"),
                    entry.get("name")
                )
            ),
            "dismissal": clean_text(
                entry.get("dismissal-text")
                or entry.get("dismissalText")
                or entry.get("dismissal")
            ),
            "runs": first_non_none(entry.get("r"), entry.get("runs")),
            "balls": first_non_none(entry.get("b"), entry.get("balls")),
            "fours": first_non_none(entry.get("4s"), entry.get("fours")),
            "sixes": first_non_none(entry.get("6s"), entry.get("sixes")),
            "strike_rate": first_non_none(entry.get("sr"), entry.get("strikeRate"))
        }

        if any(has_meaningful_value(value) for value in row.values()):
            normalized.append(row)

    return normalized


def normalize_bowling_rows(entries):
    if not isinstance(entries, list):
        return []

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        row = {
            "player": extract_person_name(
                first_non_none(
                    entry.get("bowler"),
                    entry.get("player"),
                    entry.get("name")
                )
            ),
            "overs": first_non_none(entry.get("o"), entry.get("overs")),
            "maidens": first_non_none(entry.get("m"), entry.get("maidens")),
            "runs": first_non_none(entry.get("r"), entry.get("runs")),
            "wickets": first_non_none(entry.get("w"), entry.get("wickets")),
            "no_balls": first_non_none(entry.get("nb"), entry.get("noBalls")),
            "wides": first_non_none(entry.get("wd"), entry.get("wides")),
            "economy": first_non_none(entry.get("eco"), entry.get("economy"))
        }

        if any(has_meaningful_value(value) for value in row.values()):
            normalized.append(row)

    return normalized


def normalize_scorecard(scorecard_data, score_data):
    if not isinstance(scorecard_data, list):
        return []

    summary_lookup, ordered_summaries = build_score_summary_lookup(score_data)
    normalized = []

    for index, innings in enumerate(scorecard_data):
        if not isinstance(innings, dict):
            continue

        inning_name = clean_text(
            innings.get("inning")
            or innings.get("name")
            or innings.get("team")
        )
        inning_key = normalize_inning_name(inning_name)

        summary = None
        if inning_key:
            summary = summary_lookup.get(inning_key)
        if not summary and index < len(ordered_summaries):
            summary = ordered_summaries[index]

        totals = innings.get("totals") if isinstance(innings.get("totals"), dict) else {}

        normalized_innings = {
            "inning": inning_name or (summary or {}).get("inning"),
            "runs": first_non_none(
                (summary or {}).get("runs"),
                totals.get("r"),
                totals.get("runs"),
                innings.get("r"),
                innings.get("runs")
            ),
            "wickets": first_non_none(
                (summary or {}).get("wickets"),
                totals.get("w"),
                totals.get("wickets"),
                innings.get("w"),
                innings.get("wickets")
            ),
            "overs": first_non_none(
                (summary or {}).get("overs"),
                totals.get("o"),
                totals.get("overs"),
                innings.get("o"),
                innings.get("overs")
            ),
            "batting": normalize_batting_rows(innings.get("batting")),
            "bowling": normalize_bowling_rows(innings.get("bowling"))
        }

        has_summary = any(
            has_meaningful_value(normalized_innings.get(field))
            for field in ("inning", "runs", "wickets", "overs")
        )
        if has_summary or normalized_innings["batting"] or normalized_innings["bowling"]:
            normalized.append(normalized_innings)

    return normalized


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


def find_cached_match_summary(match_id):
    cached_payload = home_matches_cache.get("payload")
    if not isinstance(cached_payload, dict):
        return None

    for collection_key in ("matches", "live_matches", "recent_matches", "upcoming_matches"):
        collection = cached_payload.get(collection_key)
        if not isinstance(collection, list):
            continue

        for match in collection:
            if not isinstance(match, dict):
                continue

            if str(match.get("id")) == str(match_id):
                return deepcopy(match)

    return None


def read_cached_match_info(match_id):
    cached = match_info_cache.get(match_id)
    if not cached:
        return None

    age_seconds = int(time.time() - cached.get("timestamp", 0.0))
    ttl_seconds = int(cached.get("ttl_seconds", MATCH_INFO_CACHE_TTL_SECONDS))
    if age_seconds > ttl_seconds:
        match_info_cache.pop(match_id, None)
        return None

    return deepcopy(cached.get("payload"))


def write_cached_match_info(match_id, payload, ttl_seconds=MATCH_INFO_CACHE_TTL_SECONDS):
    match_info_cache[match_id] = {
        "timestamp": time.time(),
        "payload": deepcopy(payload),
        "ttl_seconds": int(ttl_seconds)
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
        simplified_matches, enrichment_warning = enrich_matches_with_current_feed(simplified_matches)

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
            "warning": enrichment_warning
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
        scorecard_data, scorecard_warning = fetch_match_scorecard(match_id)
        info_data = None
        info_warning = None

        if not isinstance(scorecard_data, dict):
            info_data, info_warning = fetch_match_info(match_id)

        merged_match = {}
        if isinstance(info_data, dict):
            merged_match.update(info_data)
        if isinstance(scorecard_data, dict):
            merged_match.update(scorecard_data)

        if not merged_match:
            details = first_non_none(info_warning, scorecard_warning, "Match details are unavailable for this id")
            fallback_match = find_cached_match_summary(match_id)
            if fallback_match:
                fallback_match["id"] = fallback_match.get("id") or match_id
                fallback_match["scorecard"] = fallback_match.get("scorecard") or []
                fallback_match["details_warning"] = "Detailed scorecard is unavailable right now. Showing cached summary details."
                return jsonify({
                    "match": fallback_match,
                    "served_from_cache": True
                })

            status_code = 503 if (info_warning or scorecard_warning) else 404
            return jsonify({
                "error": "Failed to fetch match details from cricket API",
                "details": details
            }), status_code

        simplified = simplify_match(merged_match)
        if not simplified.get("id"):
            simplified["id"] = match_id

        scorecard = normalize_scorecard(merged_match.get("scorecard"), merged_match.get("score"))
        details_warning = None
        if scorecard_warning and not scorecard:
            details_warning = "Detailed scorecard is not available for this match yet."
        elif info_warning and not isinstance(info_data, dict):
            details_warning = f"Some match metadata is unavailable: {info_warning}"

        simplified["scorecard"] = scorecard
        simplified["details_warning"] = details_warning
        simplified["toss_winner"] = clean_text(merged_match.get("tossWinner"))
        simplified["toss_choice"] = clean_text(merged_match.get("tossChoice"))

        cache_ttl = MATCH_INFO_LIVE_CACHE_TTL_SECONDS if is_live_match(simplified) else MATCH_INFO_CACHE_TTL_SECONDS
        write_cached_match_info(match_id, simplified, ttl_seconds=cache_ttl)

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
