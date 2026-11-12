from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import re
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from fitparse import FitFile

if not os.environ.get("GARMIN_PERSONAL_API_KEY"):
    raise SystemExit("Missing GARMIN_PERSONAL_API_KEY repository secret.")

end_date = date.today()
# Fixed baseline: the earliest activity recovered in the full-history sync.
# Future syncs reuse this date rather than searching further back.
start_date = date(2024, 7, 14)
output = Path("output")
output.mkdir(exist_ok=True)

def run_cli(args: list[str], attempts: int = 6):
    for attempt in range(attempts):
        try:
            return subprocess.run(
                ["gc-personal", "--quiet", *args],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            output_text = (exc.stderr or exc.stdout or "")
            if "HTTP 429" not in output_text or attempt == attempts - 1:
                raise
            match = re.search(r'"retryInSeconds"\\s*:\\s*(\\d+)', output_text)
            wait_seconds = int(match.group(1)) + 2 if match else min(30 * (attempt + 1), 120)
            print(f"Garmin rate limit (429). Waiting {wait_seconds}s before retry {attempt + 2}/{attempts}.")
            time.sleep(wait_seconds)
    raise RuntimeError("Garmin CLI retry loop exhausted.")

def cli_json(*args: str):
    result = run_cli(list(args))
    return json.loads(result.stdout)

def error_text(exc):
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or exc.stdout or "").strip()
        if detail:
            return f"{exc} | CLI output: {detail[:1200]}"
    return str(exc)


def safe_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

def semicircles(value):
    return round(value * (180.0 / 2**31), 6) if value is not None else None

def parse_fit(zip_path: Path):
    with zipfile.ZipFile(zip_path) as archive:
        fit_name = next((n for n in archive.namelist() if n.lower().endswith(".fit")), None)
        if not fit_name:
            raise ValueError("No FIT file found in Garmin activity archive.")
        fit_bytes = archive.read(fit_name)

    fit = FitFile(BytesIO(fit_bytes))
    records = []
    laps = []
    sessions = []
    for message in fit.get_messages():
        values = {field.name: safe_value(field.value) for field in message}
        if message.name == "record":
            lat = values.pop("position_lat", None)
            lon = values.pop("position_long", None)
            record = {
                "time": values.get("timestamp"),
                "distance_m": values.get("distance"),
                "speed_mps": values.get("enhanced_speed") or values.get("speed"),
                "heart_rate": values.get("heart_rate"),
                "cadence_spm": values.get("cadence"),
                "power_w": values.get("power"),
                "altitude_m": values.get("enhanced_altitude") or values.get("altitude"),
                "latitude": semicircles(lat),
                "longitude": semicircles(lon),
                "temperature_c": values.get("temperature"),
                "vertical_oscillation_mm": values.get("vertical_oscillation"),
                "stance_time_ms": values.get("stance_time"),
                "step_length_mm": values.get("step_length"),
                "vertical_ratio": values.get("vertical_ratio"),
            }
            records.append(record)
        elif message.name == "lap":
            laps.append(values)
        elif message.name == "session":
            sessions.append(values)

    return {
        "record_count": len(records),
        "records": records,
        "laps": laps,
        "sessions": sessions,
    }

# Fetch all pages for the selected date range. Garmin's CLI uses a zero-based
# offset; continue until a page contains fewer than PAGE_SIZE results.
PAGE_SIZE = 100
payload = []
offset = 0
while True:
    page = cli_json(
        "activities", "--start", str(offset), "--limit", str(PAGE_SIZE),
        "--start-date", start_date.isoformat(), "--end-date", end_date.isoformat(),
    )
    if not isinstance(page, list):
        raise TypeError("Garmin activities response was not a JSON list.")
    payload.extend(page)
    if len(page) < PAGE_SIZE:
        break
    offset += PAGE_SIZE

# Keep one copy of each activity if the API returns overlapping pages.
unique = {}
for activity in payload:
    unique[str(activity["activityId"])] = activity
payload = sorted(
    unique.values(),
    key=lambda item: item.get("startTimeLocal") or item.get("startTimeGMT") or "",
)
(output / "activities.json").write_text(
    json.dumps({
        "generated_on": date.today().isoformat(),
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "source": "Garmin Connect Personal API",
        "activities": payload,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

details = []
for activity in payload:
    activity_id = int(activity["activityId"])
    sport = (activity.get("activityType") or {}).get("typeKey", "")
    item = {"activity_id": activity_id, "name": activity.get("activityName"), "type": sport}
    try:
        item["detail"] = cli_json("activity", str(activity_id))
    except Exception as exc:
        item["detail_error"] = error_text(exc)

    if sport in ("running", "treadmill_running"):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                archive_path = Path(tmp) / f"{activity_id}.zip"
                run_cli(
                    ["activity-download", str(activity_id), "-o", str(archive_path), "--force"]
                )
                item["fit"] = parse_fit(archive_path)
        except Exception as exc:
            item["fit_error"] = error_text(exc)

    details.append(item)

(output / "activity_details.json").write_text(
    json.dumps(details, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
fit_ok = sum(1 for x in details if x.get("fit", {}).get("record_count", 0))
fit_failed = [x for x in details if x.get("fit_error")]
detail_failed = [x for x in details if x.get("detail_error")]
print(f"Saved {len(payload)} activities and {len(details)} detail records.")
print(f"Activities with FIT records: {fit_ok}; FIT download failures: {len(fit_failed)}")
for item in fit_failed[:12]:
    print(f"FIT_FAILURE activity={item['activity_id']} name={item.get('name')!r}: {item['fit_error'][:1400]}")
print(f"Activity detail failures: {len(detail_failed)}")
for item in detail_failed[:8]:
    print(f"DETAIL_FAILURE activity={item['activity_id']}: {item['detail_error'][:1400]}")


# Wellness and recovery metrics, collected in monthly chunks to keep requests
# manageable and make missing endpoint/data periods visible rather than fatal.
def month_ranges(first: date, last: date):
    cursor = first.replace(day=1)
    while cursor <= last:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        chunk_end = min(last, next_month - timedelta(days=1))
        yield max(first, cursor), chunk_end
        cursor = next_month

wellness_commands = {
    "sleep_summaries": "sleep-summaries",
    "hrv_summaries": "hrv-summaries",
    "daily_summaries": "daily-summaries",
    "weight_measurements": "weight-measurements",
    "wellness_activity_summaries": "wellness-activity-summaries",
    "body_battery": "body-battery",
    "steps": "steps",
}

wellness = {}
wellness_errors = []
for output_name, command in wellness_commands.items():
    collected = []
    for chunk_start, chunk_end in month_ranges(start_date, end_date):
        try:
            result = cli_json(
                command,
                "--start-date", chunk_start.isoformat(),
                "--end-date", chunk_end.isoformat(),
            )
            collected.append({
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "data": result,
            })
        except Exception as exc:
            wellness_errors.append({
                "dataset": output_name,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "error": error_text(exc)[:1500],
            })
    wellness[output_name] = collected

(output / "wellness.json").write_text(
    json.dumps({
        "generated_on": date.today().isoformat(),
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "datasets": wellness,
        "errors": wellness_errors,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"Saved wellness datasets: {', '.join(f'{k}={len(v)} chunks' for k, v in wellness.items())}")
print(f"Wellness chunk errors: {len(wellness_errors)}")
for item in wellness_errors[:15]:
    print(f"WELLNESS_FAILURE dataset={item['dataset']} period={item['start_date']}..{item['end_date']}: {item['error'][:1400]}")
