"""Read hourly bicycle statistics from Home Assistant.

Long-term statistics are only reachable over the WebSocket API — the REST API
serves raw states, which the recorder purges after about ten days. Hourly
buckets are also the only ones kept forever: the 5-minute buckets expire with
the raw states, and aggregating those into hours is what mislabelled the
original backfill (see "Data repair" in the README). Nothing here ever asks for
period="5minute"; the hour label always comes from the bucket's own start.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import websockets

TZ = ZoneInfo("Europe/Amsterdam")
DETECTED = "sensor.bicycles_detected_total"
PASSED = "sensor.bicycles_passed_total"


def credentials() -> tuple[str, str]:
    url = os.environ.get("HOMEASSISTANT_URL") or os.environ.get("HA_URL")
    token = os.environ.get("HOMEASSISTANT_TOKEN") or os.environ.get("HA_TOKEN")
    if not url or not token:
        raise SystemExit(
            "HOMEASSISTANT_URL and HOMEASSISTANT_TOKEN are unset. These scripts are\n"
            "meant to run under `op run --env-file=...` so the token stays out of the\n"
            "shell history and out of this repository — see the README."
        )
    if token.startswith("op://"):
        raise SystemExit(
            "HOMEASSISTANT_TOKEN is still an op:// reference; 1Password did not resolve\n"
            "it. Run the script under `op run --env-file=...`."
        )
    return url.rstrip("/"), token


async def _query(start: datetime, end: datetime) -> dict:
    url, token = credentials()
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    async with websockets.connect(ws_url, max_size=None) as sock:
        await sock.recv()  # auth_required
        await sock.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(await sock.recv()).get("type") != "auth_ok":
            raise SystemExit("Home Assistant rejected the token.")
        await sock.send(json.dumps({
            "id": 1,
            "type": "recorder/statistics_during_period",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "statistic_ids": [DETECTED, PASSED],
            "period": "hour",
            "types": ["change"],
        }))
        while True:
            msg = json.loads(await sock.recv())
            if msg.get("id") == 1 and msg.get("type") == "result":
                if not msg.get("success"):
                    raise SystemExit(f"statistics query failed: {msg.get('error')}")
                return msg["result"]


def _bucket_start(value) -> datetime:
    # HA has sent epoch milliseconds since 2023; older builds send an ISO string.
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, TZ)
    return datetime.fromisoformat(value).astimezone(TZ)


def hourly(start: datetime, end: datetime) -> dict[datetime, dict]:
    """Detected and passed counts per hour, keyed by local hour start.

    `start` and `end` are inclusive of the hour they fall in on the left and
    exclusive on the right, matching how Home Assistant slices the buckets.
    An hour Home Assistant has no bucket for is absent rather than zero, so
    callers can tell "nothing passed" from "no data".
    """
    raw = asyncio.run(_query(start, end))
    out: dict[datetime, dict] = {}
    for stat_id, field in ((DETECTED, "n"), (PASSED, "p")):
        for row in raw.get(stat_id, []):
            if row.get("change") is None:
                continue
            out.setdefault(_bucket_start(row["start"]), {})[field] = int(row["change"])
    return out


def hour_start(ts: str) -> datetime:
    """The local hour a logged reading belongs to.

    Readings are stamped at :59:50, backfilled rows at :00:00; both belong to
    the hour they start in. Keeping the offset makes the two 02:00 hours of the
    October clock change distinct instants rather than one collapsed row.
    """
    return datetime.fromisoformat(ts).astimezone(TZ).replace(
        minute=0, second=0, microsecond=0)


def compare(rows: list[dict], stats: dict[datetime, dict], tolerance: int = 1) -> list[dict]:
    """Every hour where the log and Home Assistant disagree.

    `tolerance` exists because a live reading is taken at :59:50: a bicycle
    passing in the last ten seconds of an hour reaches the meter after the
    reading but still lands in Home Assistant's bucket for that hour. The log
    can therefore sit a count or two below the statistics without anything
    being wrong. It is only ever allowed to be low, never high.
    """
    logged = {hour_start(r["ts"]): r for r in rows}
    findings = []
    for hour in sorted(set(logged) | set(stats)):
        row, stat = logged.get(hour), stats.get(hour)
        if stat is None:
            continue  # outside what Home Assistant kept; nothing to check against
        if row is None:
            findings.append({"hour": hour, "kind": "missing",
                             "logged": None, "ha": stat})
            continue
        for field in ("n", "p"):
            want, got = stat.get(field), row.get(field)
            if want is None or got is None:
                continue
            short = want - got
            if short > tolerance or short < 0:
                findings.append({"hour": hour, "kind": f"{field} differs",
                                 "logged": got, "ha": want})
    return findings


def parse_local(text: str) -> datetime:
    """`2026-08-09`, `2026-08-09T14`, or a full ISO timestamp, in local time."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    return datetime.fromisoformat(text).astimezone(TZ)


def hour_range(start: datetime, end: datetime):
    """Every hour from `start` to `end` inclusive, as local hour starts.

    Stepping in UTC rather than local time: adding an hour to an aware local
    datetime does wall-clock arithmetic, which skips or repeats an hour at a
    clock change. In UTC every step is a real hour.
    """
    t, last = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    while t <= last:
        yield t.astimezone(TZ)
        t += timedelta(hours=1)
