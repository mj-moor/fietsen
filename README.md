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

## Data repair, 18 Aug 2026

Rows from 9 Aug 00:00 through 18 Aug 14:00 were rebuilt from Home Assistant's
hourly long-term statistics. The original backfill had labelled them one hour
early — yesterday's 18:00 evening peak sat at 17:00 — and the 14:00 hour on
18 Aug was lost entirely between the end of the backfill and the first live
dispatch at 15:59:50. The 4-8 Aug rows were correct and are untouched; the
break at 9 Aug is exactly the 10-day retention edge for 5-minute statistics,
which is most likely what the backfill aggregated over.

The 16:00 row on 18 Aug also had `n` = 113: the dispatch still lacked the
`gedetecteerd` field, so `append.py` fell back to `uurtotaal` during a batch
judging session. Corrected to the detector's own 43; `p` stays 113.
