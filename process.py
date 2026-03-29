import os
import logging
from datetime import datetime, timedelta, timezone, date
from flask import Flask, jsonify, request
from flask_caching import Cache
import requests
import icalendar
import recurring_ical_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CACHE_TIMEOUT = int(os.environ.get("CACHE_TIMEOUT", 300))
cache = Cache(config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": CACHE_TIMEOUT})
cache.init_app(app)

DAVMAIL_URL = os.environ.get("DAVMAIL_URL", "").strip("'\"")
GOOGLE_URL  = os.environ.get("GOOGLE_URL",  "").strip("'\"")

# Split on first colon only — passwords may contain colons
_auth_raw = os.environ.get("DAVMAIL_AUTH", "user:pass").split(":", 1)
DAVMAIL_AUTH = tuple(_auth_raw) if len(_auth_raw) == 2 else None

LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", 7))

# ---------------------------------------------------------------------------
# Sources: list of (url, auth_or_None, source_label)
# Add more entries here when you wire in new calendars — no other code changes needed.
# ---------------------------------------------------------------------------
SOURCES = [
    (DAVMAIL_URL, DAVMAIL_AUTH, "charite"),
    (GOOGLE_URL,  None,         "google"),
]

# ---------------------------------------------------------------------------
# ICS fetching & parsing
# ---------------------------------------------------------------------------
def fetch_ics(url: str, auth=None) -> icalendar.Calendar:
    """Fetch a raw ICS URL and return a parsed Calendar object."""
    resp = requests.get(url, auth=auth, timeout=30)
    resp.raise_for_status()
    return icalendar.Calendar.from_ical(resp.content)


def expand_events(cal: icalendar.Calendar, start: datetime, end: datetime) -> list:
    """Expand recurring events within [start, end)."""
    return recurring_ical_events.of(cal).between(start, end)


def serialize_event(event, source: str) -> dict:
    """
    Convert a raw iCal VEVENT into a plain dict for JSON output.
    All-day events (date objects) get ISO date strings; timed events get ISO datetimes.
    """
    raw_start = event.get("dtstart").dt
    raw_end   = event.get("dtend").dt

    # isinstance check correctly distinguishes date from datetime
    # (datetime is a subclass of date, so check datetime first)
    def to_iso(val):
        if isinstance(val, datetime):
            # Normalise to UTC so Liquid template gets consistent strings
            if val.tzinfo is not None:
                val = val.astimezone(timezone.utc)
            return val.isoformat()
        if isinstance(val, date):
            return val.isoformat()          # "2026-03-29" — all-day
        return str(val)

    return {
        "summary":  str(event.get("summary", "Untitled")),
        "start":    to_iso(raw_start),
        "end":      to_iso(raw_end),
        "location": str(event.get("location", "")),
        "source":   source,
        "all_day":  isinstance(raw_start, date) and not isinstance(raw_start, datetime),
    }


def fetch_source(url: str, auth, label: str) -> list[dict]:
    """Fetch, expand, and serialize one calendar source. Returns [] on any error."""
    if not url:
        log.warning("Source %r has no URL configured — skipping.", label)
        return []
    try:
        now = datetime.now(timezone.utc)
        cal = fetch_ics(url, auth)
        raw = expand_events(cal, now, now + timedelta(days=LOOKAHEAD_DAYS))
        events = [serialize_event(e, label) for e in raw]
        log.info("Source %r: fetched %d events.", label, len(events))
        return events
    except requests.HTTPError as e:
        log.error("HTTP error fetching %r: %s", label, e)
    except Exception as e:
        log.error("Unexpected error fetching %r: %s", label, e)
    return []


def build_payload() -> dict:
    """Fetch all sources, merge, sort, and return the final payload dict."""
    all_events = []
    for url, auth, label in SOURCES:
        all_events.extend(fetch_source(url, auth, label))

    all_events.sort(key=lambda e: e["start"])

    return {
        "last_updated": datetime.now().strftime("%H:%M"),
        "count":        len(all_events),
        "events":       all_events,
    }

# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@app.route("/events.json")
def all_events_route():
    force = request.args.get("refresh") == "true"

    if force:
        cache.delete("calendar_payload")
        log.info("Cache cleared by ?refresh=true")

    payload = cache.get("calendar_payload")
    if payload is None:
        payload = build_payload()
        cache.set("calendar_payload", payload, timeout=CACHE_TIMEOUT)
        status = "fresh"
    else:
        status = "cached"

    return jsonify({**payload, "cache_status": status})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
