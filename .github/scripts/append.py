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
    # workflow_dispatch carries no client_payload; there is nothing to append.
    raw = os.environ.get("PAYLOAD") or "null"
    p = json.loads(raw)
    if not p:
        print("no client_payload — nothing to do")
        return

    d = json.loads(DATA.read_text())

    ts = p["ts"]
    # n = detector-only count, the series every chart is built on. p adds the
    # bikes recovered by manual judging; it is recorded for the tooltip but must
    # NOT drive the charts, because judging increments at button-press time, not
    # at the time the bike passed. A batch-judging session dumps its whole total
    # into one hour (observed: 168 passed against 24 detected), and how much
    # judging happens varies by day — which would make days incomparable.
    entry = {
        "ts": ts,
        "h": int(p["uur"]),
        "n": int(p.get("gedetecteerd", p["uurtotaal"])),
        "p": int(p["uurtotaal"]),
    }

    # Idempotent per (local date, hour) rather than per instant. Keying on the
    # exact timestamp would let a mid-hour test dispatch and the real :59:50 run
    # both survive as separate rows for the same hour — one of them a partial
    # count, dragging the hour-of-day average down and double-counting the day.
    key = (ts[:10], entry["h"])
    log = [e for e in d.get("hourly", []) if (e["ts"][:10], e["h"]) != key]
    log.append(entry)
    log.sort(key=lambda e: e["ts"])

    # Trim by date rather than by count, so a gap in reporting doesn't
    # silently shorten the retained window.
    cutoff = (datetime.fromisoformat(ts) - timedelta(days=RETAIN_DAYS)).isoformat()
    log = [e for e in log if e["ts"] >= cutoff]

    d["hourly"] = log
    d["updated"] = ts
    # Totals are summed from the log rather than taken from the utility meters,
    # because the meters run on bicycles_passed_total (judging included) and the
    # charts run on detected. Taking them from different sources would let the
    # headline cards and the bars disagree on screen.
    def since(day: str, key: str = "n") -> int:
        return sum(e.get(key, e["n"]) for e in log if e["ts"][:10] >= day)

    today = datetime.fromisoformat(ts).date()
    spans = {
        "today": today.isoformat(),
        "week": (today - timedelta(days=today.weekday())).isoformat(),
        "month": today.replace(day=1).isoformat(),
    }
    d["totals"] = {k: since(v) for k, v in spans.items()}
    # Detected + judged. Kept separate so the file reconciles against the Home
    # Assistant counters, which meter bicycles_passed_total.
    d["totals_incl_judged"] = {k: since(v, "p") for k, v in spans.items()}

    DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print(f"appended {ts} h={entry['h']} n={entry['n']} ({len(log)} rows retained)")


if __name__ == "__main__":
    main()
