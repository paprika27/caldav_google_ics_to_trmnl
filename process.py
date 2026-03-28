import os
import requests
from flask import Flask, jsonify, request
from flask_caching import Cache
from datetime import datetime, timedelta
import icalendar
import recurring_ical_events

app = Flask(__name__)

# --- Cache Configuration ---
# Uses the CACHE_TIMEOUT from docker-compose (defaulting to 300s/5m if not set)
# SimpleCache is sufficient for a single-user Raspberry Pi setup.
timeout_env = int(os.environ.get('CACHE_TIMEOUT', 300))
cache = Cache(config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': timeout_env})
cache.init_app(app)

# --- Environment Variables ---
# Strip potential quotes from URLs and split the AUTH string into a (user, pass) tuple
DAVMAIL_URL = os.environ.get('DAVMAIL_URL')
GOOGLE_URL = os.environ.get('GOOGLE_URL')
AUTH_RAW = os.environ.get('DAVMAIL_AUTH', "user:pass").split(":")
AUTH = (AUTH_RAW[0], AUTH_RAW[1])

@cache.memoize(timeout=timeout_env)
def get_filtered_ics(url, auth=None):
    """
    Fetches the iCal feed, parses it, and expands recurring events.
    Memoized so we don't spam Google/DavMail on every page refresh.
    """
    # Clean up the URL in case environment variables were passed with extra quotes
    clean_url = url.strip('"').strip("'")
    
    # Fetch the raw ICS file with a 30s timeout to prevent hanging the app
    resp = requests.get(clean_url, auth=auth, timeout=30)
    resp.raise_for_status() # Crashes gracefully if 401 Unauthorized or 404
    
    # Load the ICS into the icalendar object
    cal = icalendar.Calendar.from_ical(resp.content)
    
    # Filter Window: Start Now, look ahead 7 days.
    # recurring_ical_events is CRITICAL here: it turns "Every Friday" into 
    # actual individual event instances for the given range.
    start = datetime.now()
    end = start + timedelta(days=7)
    return recurring_ical_events.of(cal).between(start, end)

def process_events(event_list, source_name):
    """
    Transforms raw iCal event objects into clean dictionaries for JSON output.
    """
    processed = []
    for event in event_list:
        # Extract the datetime objects for start and end
        start_dt = event.get('dtstart').dt
        end_dt = event.get('dtend').dt
        
        processed.append({
            "summary": str(event.get('summary')),
            # Check if dt is a datetime (with time) or just a date (all-day event)
            # then convert to ISO 8601 string for the Liquid template
            "start": start_dt.isoformat() if hasattr(start_dt, 'isoformat') else str(start_dt),
            "end": end_dt.isoformat() if hasattr(end_dt, 'isoformat') else str(end_dt),
            "source": source_name # Added so Liquid can color-code by source
        })
    return processed

@cache.memoize(timeout=timeout_env)
def get_data_from_sources():
    """
    The main endpoint called by Larapaper/TRMNL.
    Supports a ?refresh=true query parameter to force a cache clear.
    """
    if request.args.get('refresh') == 'true':
        cache.clear()

    # Fetch and expand both calendars
    davmail_raw = get_filtered_ics(DAVMAIL_URL, AUTH)
    google_raw = get_filtered_ics(GOOGLE_URL)

    # 1. Process both lists into our standard format
    # 2. Combine them into one large list
    # 3. Sort them chronologically by start time
    combined = sorted(
        process_events(davmail_raw, "davmail") + process_events(google_raw, "google"),
        key=lambda x: x['start']
    )
    
    # Capture the 'generation' time
    sync_time = datetime.now().strftime("%H:%M")
    
    # Return the final JSON structure expected by our Liquid template
    return {
        "sync_time": sync_time,
        "events": combined
    }
        
@app.route('/events.json')
def all_events():
    if request.args.get('refresh') == 'true':
        cache.clear()

    # This call will either hit the cache or trigger the fetch above
    cached_data = get_data_from_sources()

    return jsonify({
        "last_updated": cached_data["sync_time"], # Reflects ACTUAL fetch time, not downstream poll time
        "count": len(cached_data["events"]),
        "events": cached_data["events"]
    })
    
if __name__ == '__main__':
    # Runs on port 80 inside the container (mapped to 1090 on the Pi host)
    app.run(host='0.0.0.0', port=80)
