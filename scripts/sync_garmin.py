from __future__ import annotations

import json
import os
import subprocess
import tempfile
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

def cli_json(*args: str):
    result = subprocess.run(
        ["gc-personal", "--quiet", *args],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)

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
        item["detail_error"] = str(exc)

    if sport in ("running", "treadmill_running"):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                archive_path = Path(tmp) / f"{activity_id}.zip"
                subprocess.run(
                    ["gc-personal", "--quiet", "activity-download", str(activity_id),
                     "-o", str(archive_path), "--force"],
                    check=True, capture_output=True, text=True,
                )
                item["fit"] = parse_fit(archive_path)
        except Exception as exc:
            item["fit_error"] = str(exc)

    details.append(item)

(output / "activity_details.json").write_text(
    json.dumps(details, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"Saved {len(payload)} activities and {len(details)} detail records.")
print(f"Activities with FIT records: {sum(1 for x in details if x.get('fit', {}).get('record_count', 0))}")


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
    "stress": "stress",
    "steps": "steps",
    "hydration": "hydration",
    "body_battery": "body-battery",
    "weight_measurements": "weight-measurements",
    "wellness_activity_summaries": "wellness-activity-summaries",
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
                "error": str(exc)[:500],
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
