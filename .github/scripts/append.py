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
from datetime import datetime, timedelta, timezone

RETAIN_DAYS = 90
DATA = pathlib.Path(__file__).resolve().parents[2] / "data.json"


def hour_key(ts: str) -> str:
    """The UTC instant of the hour a reading belongs to.

    Readings are stamped at :59:50 and backfilled rows at :00:00; both belong to
    the hour they start in. Going through UTC makes the two local 02:00 hours of
    the October clock change distinct.
    """
    t = datetime.fromisoformat(ts).replace(minute=0, second=0, microsecond=0)
    return t.astimezone(timezone.utc).isoformat()


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

    # Idempotent per hour-instant. Keying on the exact timestamp would let a
    # mid-hour test dispatch and the real :59:50 run both survive as separate
    # rows for the same hour — one of them a partial count, dragging the
    # hour-of-day average down and double-counting the day. Keying on
    # (local date, hour) collapses those correctly but also collapses the two
    # 02:00 hours when the clocks go back in October, silently dropping one of
    # them; the UTC instant of the hour start keeps those apart while still
    # matching every dispatch made within the same hour.
    key = hour_key(ts)
    log = [e for e in d.get("hourly", []) if hour_key(e["ts"]) != key]
    log.append(entry)
    log.sort(key=lambda e: e["ts"])

    # Trim by date rather than by count, so a gap in reporting doesn't
    # silently shorten the retained window.
    cutoff = (datetime.fromisoformat(ts) - timedelta(days=RETAIN_DAYS)).isoformat()
    log = [e for e in log if e["ts"] >= cutoff]

    d["hourly"] = log
    d["updated"] = ts
    # Totals come from the Home Assistant utility meters, NOT from summing the
    # log. The log is only ever a subset of reality: it begins 4 Aug 17:00 when
    # hourly statistics started, and any hour whose dispatch fails leaves a hole
    # that a sum can never recover. The meters are authoritative and self-heal,
    # so the cards always agree with Home Assistant.
    #
    # totals            = detector only
    # totals_incl_judged = detector + manually confirmed (what the meters on
    #                      bicycles_passed_total measure)
    # GitHub caps client_payload at 10 top-level properties, so the meter values
    # arrive nested under `incl` (detector + manually confirmed) and `det`
    # (detector only). The flat form is still accepted so a half-updated
    # configuration keeps working.
    def group(name: str, *flat: str) -> dict:
        g = p.get(name)
        if isinstance(g, dict):
            return {k: int(v) for k, v in g.items() if v is not None}
        keys = ("dag", "week", "maand", "totaal")
        return {k: int(p[f]) for k, f in zip(keys, flat) if p.get(f) is not None}

    incl = group("incl", "dagtotaal", "weektotaal", "maandtotaal", "totaal")
    det = group("det", "gedetecteerd_dagtotaal", "gedetecteerd_weektotaal",
                "gedetecteerd_maandtotaal", "totaal_gedetecteerd")

    def spans(g: dict) -> dict:
        return {"today": g["dag"], "week": g["week"], "month": g["maand"]}

    if {"dag", "week", "maand"} <= incl.keys():
        d["totals_incl_judged"] = spans(incl)
    if {"dag", "week", "maand"} <= det.keys():
        # The detector-only meters were created on 18 Aug, so for their first
        # cycle they report far less than actually happened and would make the
        # split read "2 automatisch, 307 handmatig". Both the meter and the log
        # sum are undercounts of the same quantity — the meter because it started
        # late, the log because it starts 4 Aug 17:00 and drops failed hours — so
        # take whichever is larger. The meters win once they have run a full
        # cycle (daily from 19 Aug, weekly from Mon, monthly from 1 Sep) and this
        # becomes a no-op.
        def logged(since: str) -> int:
            return sum(e["n"] for e in log if e["ts"][:10] >= since)

        today = datetime.fromisoformat(ts).date()
        floors = {
            "today": logged(today.isoformat()),
            "week": logged((today - timedelta(days=today.weekday())).isoformat()),
            "month": logged(today.replace(day=1).isoformat()),
        }
        d["totals"] = {k: max(v, floors[k]) for k, v in spans(det).items()}
    if "totaal" in incl:
        d["lifetime"] = {"n": det.get("totaal", incl["totaal"]), "p": incl["totaal"]}

    DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print(f"appended {ts} h={entry['h']} n={entry['n']} ({len(log)} rows retained)")


if __name__ == "__main__":
    main()
