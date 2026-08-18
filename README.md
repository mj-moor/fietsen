# fietsen.gouwplein.nl

Static page showing the automatic bicycle count on the Gouwplein in Weesp,
published with GitHub Pages.

## How it updates

Home Assistant fires a `repository_dispatch` (`event_type: bike-counts`) once
an hour at **:59:50**. The timing matters: `sensor.bicycles_this_hour` is a
utility meter that resets at the top of the hour, so a trigger at `:00` would
log an empty bucket every time.

`.github/workflows/append.yml` catches the dispatch, runs
`.github/scripts/append.py` to append the reading to `data.json`, and commits.
The read-modify-write lives here rather than in Home Assistant so the JSON
surgery stays out of Jinja templates.

Payload:

```json
{
  "ts": "2026-08-18T13:59:50+02:00",
  "uur": 13,
  "uurtotaal": 17,
  "dagtotaal": 147,
  "weektotaal": 749,
  "maandtotaal": 8093
}
```

`ts` is Home Assistant's own timestamp, not the runner's — the Action starts
seconds later and in UTC, which would smear readings across hour boundaries.
It also acts as the dedupe key, so a replayed dispatch updates its row instead
of double-counting.

`data.json` keeps 90 days of hourly readings; the page derives the hour-of-day
profile and the daily totals from that log.

## Counting caveat

Detection misses an estimated 17–23% of passes, roughly flat across volume, and
only the near lane is counted. The published figures are therefore a consistent
undercount rather than a true total. See
[the write-up](https://www.mjmoor.nl/) for how it is built.
