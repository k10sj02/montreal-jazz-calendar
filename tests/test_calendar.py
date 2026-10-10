from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar

from montreal_jazz_calendar import build_calendar, merge_state, parse_events

SAMPLE = '''
<script type="application/ld+json">{"@context":"http://schema.org","@type":"Event","@id":"event_42_0","eventStatus":"https://schema.org/EventScheduled","name":"Jazz Trio","url":"https://example.com/event","startDate":"2026-10-12T20:30-4:00","endDate":"2026-10-12T22:30-4:00","location":[{"@type":"Place","name":"Jazz Room","address":{"@type":"PostalAddress","streetAddress":"123 St-Denis<br>Montréal"}}]}</script>
'''


def test_parse_structured_event():
    event = parse_events(SAMPLE)[0]
    assert event.title == "Jazz Trio"
    assert event.start == "2026-10-12T20:30:00-04:00"
    assert event.venue == "Jazz Room"
    assert event.address == "123 St-Denis Montréal"


def test_ics_and_stable_uid(tmp_path: Path):
    event = parse_events(SAMPLE)[0]
    now = datetime(2026, 10, 10, 12, tzinfo=ZoneInfo("America/Toronto"))
    merged = merge_state([event], tmp_path / "state.json", now)
    output = build_calendar(merged, now)
    calendar = Calendar.from_ical(output)
    vevent = next(component for component in calendar.walk() if component.name == "VEVENT")
    assert str(vevent["UID"]) == event.uid
    assert str(vevent["SUMMARY"]) == "Jazz Trio"
