from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

# Keep the first import small and safe: the official Garmin Personal API
# client handles API-key exchange and authenticated requests.
if not os.environ.get("GARMIN_PERSONAL_API_KEY"):
    raise SystemExit("Missing GARMIN_PERSONAL_API_KEY repository secret.")

end_date = date.today()
start_date = end_date - timedelta(days=90)

command = [
    "gc-personal",
    "--quiet",
    "activities",
    "--start",
    "0",
    "--limit",
    "100",
    "--start-date",
    start_date.isoformat(),
    "--end-date",
    end_date.isoformat(),
]

result = subprocess.run(command, check=True, capture_output=True, text=True)
payload = json.loads(result.stdout)

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)
output_file = output_dir / "activities.json"
output_file.write_text(
    json.dumps(
        {
            "generated_on": date.today().isoformat(),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "source": "Garmin Connect Personal API",
            "activities": payload,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

print(f"Export created: {output_file}")
