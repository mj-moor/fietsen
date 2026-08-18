#!/usr/bin/env python3
"""Check data.json against Home Assistant's hourly statistics.

Home Assistant is the record of what actually happened; data.json is a copy
that can drift — a dispatch that never fired leaves a hole, and a backfill can
put an hour in the wrong slot. This prints every hour where the two disagree
and exits non-zero if any do.

Run it when something in the counting chain changed — new or renamed meters, an
edited dispatch payload, after a backfill, or when a chart looks wrong. Not on a
timer: a failed dispatch leaves a hole the page already shows as an incomplete
day, and a check that reports "OK" every week is one you stop reading.

    op run --env-file=<your ha env file> -- python3 scripts/verify.py

Reads only. It never writes data.json and never touches Home Assistant.
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta

import hastats
from hastats import TZ

DATA = pathlib.Path(__file__).resolve().parents[1] / "data.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="only check from this date/hour (local), e.g. 2026-08-09")
    ap.add_argument("--tolerance", type=int, default=1,
                    help="counts the log may sit below Home Assistant (default 1); "
                         "a reading taken at :59:50 misses the last ten seconds")
    args = ap.parse_args()

    rows = json.loads(DATA.read_text())["hourly"]
    if not rows:
        print("data.json holds no hourly rows.")
        return 1

    start = hastats.hour_start(min(r["ts"] for r in rows))
    if args.since:
        start = max(start, hastats.parse_local(args.since))
    # The hour in progress is not comparable: the log gets it at :59:50 and the
    # statistics bucket is still filling.
    end = datetime.now(TZ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    if end < start:
        print("Nothing complete enough to check yet.")
        return 0

    rows = [r for r in rows if start <= hastats.hour_start(r["ts"]) <= end]
    stats = {h: v for h, v in hastats.hourly(start, end + timedelta(hours=1)).items()
             if start <= h <= end}
    findings = hastats.compare(rows, stats, args.tolerance)

    span = f"{start:%d %b %H:%M} – {end:%d %b %H:%M}"
    if not findings:
        print(f"OK: {len(rows)} hours over {span} agree with Home Assistant.")
        return 0

    print(f"{len(findings)} of {len(stats)} hours over {span} disagree:\n")
    for f in findings:
        if f["kind"] == "missing":
            ha = f["ha"]
            print(f"  {f['hour']:%Y-%m-%d %H:00}  missing from data.json "
                  f"(Home Assistant has n={ha.get('n')} p={ha.get('p')})")
        else:
            print(f"  {f['hour']:%Y-%m-%d %H:00}  {f['kind']}: "
                  f"data.json {f['logged']}, Home Assistant {f['ha']}")
    print("\nRepair a range with:  python3 scripts/backfill.py --from ... --to ...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
