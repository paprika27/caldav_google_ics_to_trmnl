# CalDAV & Google ICS to TRMNL Stack

This repository provides a full Docker-based stack to bridge enterprise calendars (Outlook/Exchange via DavMail) and Google Calendars to your TRMNL device (KOreader plugin on Kobo, in my case) using [BYOS Larapaper](https://github.com/usetrmnl/larapaper).

Larapaper doesn’t natively support calendar plugins like the official `oem-calendar` plugin (written in Ruby). The existing plugins rely on this core dependency, making it impossible to import calendars directly. There is now a seed holidays ics recipe but this is no solution because
- **Exchange (EWS)**: Even translated into CalDav by `davmail` needs login credentials.
- **Google Calendar**: Private `.ics` files are unfiltered and crash Larapaper’s frontend if not preprocessed.

**Solution**: Built a proxy service (`ical-proxy`) that:
  - Fetches calendars from both EWS (via DavMail) and Google ICS links.
  - Filters events to the next 7 days.
  - Converts them into JSON format for Larapaper consumption.
  - Caches responses to avoid timeouts caused by slow Exchange APIs.

## Components
1. **DavMail**: Acts as a gateway for Microsoft Exchange (when the admin does not give you direct CalDav).
2. **Python Script**: Aggregates DavMail and Google private ICS sources, adds metadata, filters for the next 7 days, and formats them for the TRMNL Liquid template (as json).
3. **Larapaper**: A local instance of the TRMNL server to host your private plugins.

## Setup
1. **Clone the repo**:
   ```bash
   git clone [https://github.com/paprika27/caldav_google_ics_to_trmnl](https://github.com/paprika27/caldav_google_ics_to_trmnl)
   cd caldav_google_ics_to_trmnl
   ```
2. **Configure Environment**:
   Update the `docker-compose.yml` with your email, passwords, and URLs.
3. **Run the Stack**:
   ```bash
   docker-compose up -d
   ```

## TRMNL Integration
Use this stack in conjunction with the [Upcoming ICS Template](https://github.com/paprika27/trmnlp_upcoming_ics) to render the timeline on your device.

## License
MIT
```
