# Greater Montréal Jazz Calendar

An automatically updated, subscribable calendar generated from the public [sortiesJAZZnights Greater Montréal calendar](https://sortiesjazznights.com/calendrier-jazz-du-grand-montreal/).

The feed preserves event titles, start and end times, venues, addresses, and source links. It refreshes every six hours and retains previously seen events when a source fetch fails.

## Run locally

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
montreal-jazz-calendar
```

This project is independent and is not affiliated with sortiesJAZZnights or the listed venues.
