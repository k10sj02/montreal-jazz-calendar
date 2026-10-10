from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

SOURCE_URL = "https://sortiesjazznights.com/calendrier-jazz-du-grand-montreal/"
TIMEZONE = ZoneInfo("America/Toronto")
USER_AGENT = "MontrealJazzCalendar/1.0 (+https://github.com/k10sj02/montreal-jazz-calendar)"


@dataclass(frozen=True)
class JazzEvent:
    source_id: str
    title: str
    start: str
    end: str
    venue: str
    address: str
    url: str
    status: str = "CONFIRMED"

    @property
    def uid(self) -> str:
        value = f"{self.source_id}|{self.start}"
        return hashlib.sha256(value.encode()).hexdigest()[:24] + "@montreal-jazz-calendar"


def _parse_datetime(value: str) -> datetime:
    # EventON emits offsets such as -4:00; ISO 8601 requires -04:00.
    value = re.sub(r"([+-])(\d):(\d{2})$", r"\g<1>0\2:\3", value)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def parse_events(html: str) -> list[JazzEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[JazzEvent] = []
    seen: set[tuple[str, str]] = set()
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if '"@type": "Event"' not in raw and '"@type":"Event"' not in raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "Event" or not data.get("startDate"):
            continue
        start = _parse_datetime(data["startDate"])
        end = _parse_datetime(data.get("endDate") or data["startDate"])
        locations = data.get("location") or []
        if isinstance(locations, dict):
            locations = [locations]
        location = locations[0] if locations else {}
        address_data = location.get("address") or {}
        address = address_data.get("streetAddress", "") if isinstance(address_data, dict) else str(address_data)
        address = BeautifulSoup(address, "html.parser").get_text(" ", strip=True)
        source_id = str(data.get("@id") or data.get("url") or data.get("name"))
        key = (source_id, start.isoformat())
        if key in seen:
            continue
        seen.add(key)
        events.append(JazzEvent(
            source_id=source_id,
            title=BeautifulSoup(str(data.get("name", "Jazz event")), "html.parser").get_text(" ", strip=True),
            start=start.isoformat(),
            end=end.isoformat(),
            venue=BeautifulSoup(str(location.get("name", "")), "html.parser").get_text(" ", strip=True),
            address=address,
            url=str(data.get("url") or SOURCE_URL),
            status="CANCELLED" if "Cancelled" in str(data.get("eventStatus")) else "CONFIRMED",
        ))
    if not events:
        raise ValueError("No jazz events found in source page")
    return sorted(events, key=lambda event: (event.start, event.title))


def merge_state(current: list[JazzEvent], state_path: Path, now: datetime) -> list[JazzEvent]:
    old: dict[str, dict] = {}
    if state_path.exists():
        try:
            old = json.loads(state_path.read_text()).get("events", {})
        except (json.JSONDecodeError, OSError):
            old = {}
    merged = {event.uid: {**asdict(event), "missing_runs": 0} for event in current}
    for uid, item in old.items():
        if uid in merged:
            continue
        try:
            start = datetime.fromisoformat(item["start"])
        except (KeyError, ValueError):
            continue
        missing = int(item.get("missing_runs", 0)) + 1
        if start >= now - timedelta(days=1) and missing < 2:
            merged[uid] = {**item, "missing_runs": missing}
        elif start >= now - timedelta(days=1) and item.get("status") != "CANCELLED":
            merged[uid] = {**item, "status": "CANCELLED", "missing_runs": missing}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"updated": now.isoformat(), "events": merged}, ensure_ascii=False, indent=2) + "\n")
    return [JazzEvent(**{k: value for k, value in item.items() if k != "missing_runs"}) for item in merged.values()]


def build_calendar(events: list[JazzEvent], generated: datetime) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Greater Montréal Jazz Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Greater Montréal Jazz")
    calendar.add("x-wr-timezone", "America/Toronto")
    calendar.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    for item in sorted(events, key=lambda event: (event.start, event.title)):
        event = Event()
        event.add("uid", item.uid)
        event.add("dtstamp", generated)
        event.add("dtstart", datetime.fromisoformat(item.start))
        event.add("dtend", datetime.fromisoformat(item.end))
        event.add("summary", item.title)
        location = ", ".join(part for part in (item.venue, item.address) if part)
        if location:
            event.add("location", location)
        event.add("description", f"Source: sortiesJAZZnights\n{item.url}")
        event.add("url", item.url)
        event.add("status", item.status)
        event.add("categories", "Jazz")
        calendar.add_component(event)
    return calendar.to_ical()


def main() -> None:
    root = Path.cwd()
    now = datetime.now(TIMEZONE)
    response = httpx.get(SOURCE_URL, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=45)
    response.raise_for_status()
    current = parse_events(response.text)
    events = merge_state(current, root / "data/state.json", now)
    public = root / "public"
    public.mkdir(exist_ok=True)
    (public / "montreal-jazz.ics").write_bytes(build_calendar(events, now))
    status = {
        "generated": now.isoformat(),
        "count": sum(event.status != "CANCELLED" for event in events),
        "cancelled": sum(event.status == "CANCELLED" for event in events),
        "source": SOURCE_URL,
    }
    (public / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    print(f"Published {status['count']} jazz events ({status['cancelled']} cancelled).")
