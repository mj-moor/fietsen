#!/usr/bin/env python3
"""Rebuild a range of hourly rows in data.json from Home Assistant.

Use after a failed dispatch leaves a hole, or when verify.py reports hours that
disagree. Rows are rebuilt from the hourly statistics rather than shifted or
interpolated, so every published hour is a measured hour.

    op run --env-file=<your ha env file> -- \
        python3 scripts/backfill.py --from 2026-08-09 --to 2026-08-18T14

The range is inclusive on both ends and given in local time; `--to 2026-08-18T14`
means the 14:00–15:00 hour is the last one rewritten. Rows outside the range are
left exactly as they are.

Two things this deliberately does NOT do, because the original backfill got them
wrong (see "Data repair" in the README):

  - It never aggregates 5-minute buckets into hours. Those expire with the raw
    states after ten days, and grouping them is what shifted every hour from
    9 August onwards one slot early.
  - It never trusts its own arithmetic. After writing, it asks Home Assistant
    again and compares the file it just wrote; on any disagreement it restores
    the original and exits non-zero.
"""
import argparse
import json
import pathlib
import sys
from datetime import timedelta

import hastats
from hastats import TZ

DATA = pathlib.Path(__file__).resolve().parents[1] / "data.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True,
                    help="first hour to rebuild, local (2026-08-09 or 2026-08-09T14)")
    ap.add_argument("--to", dest="end", required=True, help="last hour to rebuild, local")
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    args = ap.parse_args()

    start, end = hastats.parse_local(args.start), hastats.parse_local(args.end)
    if end < start:
        raise SystemExit("--to is before --from")

    stats = hastats.hourly(start, end + timedelta(hours=1))
    stats = {h: v for h, v in stats.items() if start <= h <= end}
    if not stats:
        raise SystemExit("Home Assistant has no statistics for that range; nothing to rebuild.")

    data = json.loads(DATA.read_text())
    before = {hastats.hour_start(r["ts"]): r for r in data["hourly"]}

    rebuilt = []
    for hour in hastats.hour_range(start, end):
        stat = stats.get(hour)
        if stat is None:
            # An hour Home Assistant has nothing for stays as it is rather than
            # being overwritten with a zero it never measured.
            if hour in before:
                rebuilt.append(before[hour])
            continue
        n = stat.get("n", 0)
        rebuilt.append({"ts": hour.isoformat(), "h": hour.hour, "n": n,
                        "p": max(stat.get("p", n), n)})

    kept = [r for r in data["hourly"] if not (start <= hastats.hour_start(r["ts"]) <= end)]
    log = sorted(kept + rebuilt, key=lambda r: hastats.hour_start(r["ts"]))

    changed = [r for r in rebuilt
               if before.get(hastats.hour_start(r["ts"]), {}).get("n") != r["n"]
               or before.get(hastats.hour_start(r["ts"]), {}).get("p") != r["p"]]
    print(f"{len(rebuilt)} hours in range, {len(changed)} of them change:")
    for r in changed[:40]:
        was = before.get(hastats.hour_start(r["ts"]))
        old = f"n={was['n']} p={was['p']}" if was else "absent"
        print(f"  {r['ts'][:13]}:00  {old:>16}  ->  n={r['n']} p={r['p']}")
    if len(changed) > 40:
        print(f"  ... and {len(changed) - 40} more")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not changed:
        print("\nNothing to write.")
        return 0

    original = DATA.read_text()
    data["hourly"] = log
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")

    # Round trip: re-read the file and re-ask Home Assistant, rather than
    # checking the numbers still held in memory.
    written = [r for r in json.loads(DATA.read_text())["hourly"]
               if start <= hastats.hour_start(r["ts"]) <= end]
    fresh = {h: v for h, v in hastats.hourly(start, end + timedelta(hours=1)).items()
             if start <= h <= end}
    findings = hastats.compare(written, fresh, tolerance=0)
    if findings:
        DATA.write_text(original)
        print(f"\n{len(findings)} hours still disagree after writing; data.json restored.")
        for f in findings[:10]:
            print(f"  {f['hour']:%Y-%m-%d %H:00}  {f['kind']}: "
                  f"wrote {f['logged']}, Home Assistant {f['ha']}")
        return 1

    print(f"\nWrote {len(changed)} hours; all {len(written)} rows in range re-verified "
          f"against Home Assistant. Commit data.json to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
