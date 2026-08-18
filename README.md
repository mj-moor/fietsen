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

## Checking and repairing the log

Home Assistant is the record of what happened; `data.json` is a copy that can
drift. Two scripts under `scripts/` keep them honest. Both need
`HOMEASSISTANT_URL` and `HOMEASSISTANT_TOKEN` in the environment and read the
WebSocket API — long-term statistics are not on the REST API. Neither writes
anything to Home Assistant. Run them under `op run` so the token never lands in
a file or in shell history:

```bash
op run --env-file=<env file holding those two vars> -- python3 scripts/verify.py
op run --env-file=<env file holding those two vars> -- \
    python3 scripts/backfill.py --from 2026-08-09 --to 2026-08-18T14 --dry-run
```

`verify.py` prints every hour where `data.json` and Home Assistant disagree and
exits non-zero if any do. Run it when something in the counting chain changed —
new or renamed meters, an edited dispatch payload, after a backfill, or when a
chart looks wrong — rather than on a timer. A failed dispatch leaves a hole the
page already marks as an incomplete day, and a weekly "OK" is a check you stop
reading. It allows the log to sit up to `--tolerance` (default
1) below Home Assistant: the reading is taken at :59:50, so a bicycle in the
last ten seconds of an hour reaches the meter after the reading but still lands
in Home Assistant's bucket. The log is never allowed to read high.

`backfill.py` rewrites a range of hours, inclusive on both ends, in local time.
It only ever writes hours Home Assistant has statistics for, leaves everything
outside the range untouched, and after writing re-asks Home Assistant and
compares the file it just wrote — restoring the original if anything disagrees.
Start with `--dry-run`.

Both take the hour label from the statistics bucket's own start and only ever
ask for hourly buckets. The 5-minute buckets expire with the raw states after
about ten days, and aggregating those is what went wrong below.

`websockets` is the only dependency beyond the standard library.

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

## Clock changes

Readings are deduplicated per hour-instant in UTC, not per (date, hour). When
the clocks go back in October a date has two 02:00 hours; keying on the local
hour would have let the second silently overwrite the first. The page adds any
rows that share an hour slot into one bar, so that day's total stays right even
though the heatmap has 24 columns for 25 hours. In March the missing 02:00
simply has no row, and the day reads as incomplete.
