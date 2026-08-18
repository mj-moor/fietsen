#!/usr/bin/env python3
"""Append one hourly reading to data.json.

Reads the repository_dispatch client_payload from $PAYLOAD. Home Assistant
sends its own timestamp — the Action runs seconds later and in UTC, so using
the runner clock would smear readings across hour boundaries.

The hourly log is the only durable record; totals are a convenience snapshot
for the headline cards. The page derives everything else from `hourly`.
"""
import json
import os
import pathlib
from datetime import datetime, timedelta

RETAIN_DAYS = 90
DATA = pathlib.Path(__file__).resolve().parents[2] / "data.json"


def main() -> None:
    p = json.loads(os.environ["PAYLOAD"])
    d = json.loads(DATA.read_text())

    ts = p["ts"]
    entry = {"ts": ts, "h": int(p["uur"]), "n": int(p["uurtotaal"])}

    # Idempotent: a retried dispatch must not double-count the same hour.
    log = [e for e in d.get("hourly", []) if e["ts"] != ts]
    log.append(entry)
    log.sort(key=lambda e: e["ts"])

    # Trim by date rather than by count, so a gap in reporting doesn't
    # silently shorten the retained window.
    cutoff = (datetime.fromisoformat(ts) - timedelta(days=RETAIN_DAYS)).isoformat()
    log = [e for e in log if e["ts"] >= cutoff]

    d["hourly"] = log
    d["updated"] = ts
    d["totals"] = {
        "today": int(p["dagtotaal"]),
        "week": int(p["weektotaal"]),
        "month": int(p["maandtotaal"]),
    }

    DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print(f"appended {ts} h={entry['h']} n={entry['n']} ({len(log)} rows retained)")


if __name__ == "__main__":
    main()
