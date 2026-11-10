"""Gera output/performance.html (Performance Center) a partir dos JSONs do sync.

Entradas (output/): activities.json, activity_details.json, wellness.json (opcional).
Saída: output/performance.html — HTML único, sem CDN, sem chamadas de rede.
Não acessa a API da Garmin.
"""
from __future__ import annotations
import json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

root = Path("output")
template = Path(__file__).with_name("performance_template.html")

activities = json.loads((root / "activities.json").read_text(encoding="utf-8"))["activities"]
details = json.loads((root / "activity_details.json").read_text(encoding="utf-8"))
by_id = {str(x.get("activity_id")): x for x in details}


def num(v, nd=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


# ---------- atividades ----------
rows = []
for a in activities:
    kind = (a.get("activityType") or {}).get("typeKey", "")
    if kind not in ("running", "treadmill_running"):
        continue
    start = (a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:19].replace("Z", "")
    try:
        dt = datetime.fromisoformat(start)
    except ValueError:
        continue
    dist_m, dur = a.get("distance"), a.get("duration")
    if not dist_m or not dur or dist_m < 100:
        continue
    fit = (by_id.get(str(a.get("activityId"))) or {}).get("fit", {})
    flat = []
    for lap in fit.get("laps", []) or []:
        d, t, hr = lap.get("total_distance"), lap.get("total_timer_time"), lap.get("avg_heart_rate")
        if d is None or t is None:
            continue
        flat += [round(d / 1000, 2), round(t), round(hr) if isinstance(hr, (int, float)) else None]
    rows.append([
        dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"),
        "T" if kind == "treadmill_running" else "R",
        (a.get("activityName") or "Corrida").strip(),
        round(dist_m / 1000, 2), round(dur),
        round(a.get("averageHR") or 0) or None, round(a.get("maxHR") or 0) or None,
        flat,
    ])
# sem FC não dá para calcular carga/eficiência: usa 0 -> o painel ignora via isEasy; mantém o treino na lista
rows = [r[:6] + [r[6] or 0, r[7] or 0, r[8]] for r in rows]
rows.sort(key=lambda r: (r[0], r[1]), reverse=True)

# ---------- recuperação (mesma extração do build_dashboard.py) ----------
sleep_m, rec_rows, k = [], [], {}
wp = root / "wellness.json"
if wp.exists():
    datasets = json.loads(wp.read_text(encoding="utf-8")).get("datasets", {})

    def flatten(name, list_key=None):
        out = []
        for chunk in datasets.get(name, []):
            data = chunk.get("data")
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict):
                if list_key and isinstance(data.get(list_key), list):
                    out.extend(data[list_key])
                else:
                    for v in data.values():
                        if isinstance(v, list):
                            out.extend(v)
        return out

    sl = {x["calendarDate"]: x for x in flatten("sleep_summaries") if x.get("calendarDate")}
    hv = {x["calendarDate"]: x for x in flatten("hrv_summaries", "hrvSummaries") if x.get("calendarDate")}
    dy = {x["calendarDate"]: x for x in flatten("daily_summaries", "data") if x.get("calendarDate")}

    sh = {d: x["sleepTimeSeconds"] / 3600 for d, x in sl.items() if x.get("sleepTimeSeconds")}
    ss = {d: num((((x.get("sleepScores") or {}).get("overall") or {}).get("value"))) for d, x in sl.items()}
    hrv = {d: num(x.get("lastNightAvg")) for d, x in hv.items()}
    hrv7 = {d: num(x.get("weeklyAvg")) for d, x in hv.items()}
    bb = {d: num((x.get("bodyBattery") or {}).get("latestValue")) for d, x in dy.items()}
    st = {d: num((x.get("stress") or {}).get("avgLevel")) for d, x in dy.items()}
    rhr = {d: num((x.get("heartRate") or {}).get("restingValue")) for d, x in dy.items()}
    stp = {d: num((((x.get("movement") or {}).get("steps") or {}).get("value"))) for d, x in dy.items()}
    sp = {d: num((x.get("pulseOx") or {}).get("avgValue")) for d, x in dy.items()}
    rs = {d: num((x.get("respiration") or {}).get("avgValue")) for d, x in dy.items()}

    days = sorted(set(sl) | set(hv) | set(dy))
    months = defaultdict(list)
    for d in days:
        months[d[:7]].append(d)

    def avg(m, ds, nd=1):
        v = [m.get(d) for d in ds if isinstance(m.get(d), (int, float))]
        return round(sum(v) / len(v), nd) if v else None

    for mo, ds in sorted(months.items(), reverse=True):
        sleep_m.append([mo, avg(sh, ds), avg(ss, ds, 0), avg(hrv, ds, 0), avg(bb, ds, 0), avg(st, ds, 0), avg(rhr, ds, 0)])
    for d in days:
        if any(isinstance(m.get(d), (int, float)) for m in (ss, hrv, bb)):
            rec_rows.append([d, ss.get(d), hrv.get(d), bb.get(d)])

    def latest(m):
        v = [(d, x) for d, x in m.items() if isinstance(x, (int, float))]
        return max(v) if v else (None, None)

    ds_, sv = latest(sh)
    k = {
        "sono": f"{sv:.1f} h" if sv is not None else "—", "score": latest(ss)[1], "vfc": latest(hrv)[1],
        "vfc7": latest(hrv7)[1], "bb": latest(bb)[1], "estresse": latest(st)[1], "fcr": latest(rhr)[1],
        "passos": latest(stp)[1], "spo2": latest(sp)[1], "resp": latest(rs)[1], "data": ds_ or max(days, default=None),
    }

raw = {"a": rows, "m": sleep_m, "r": rec_rows, "k": k,
       "src": f"Garmin Connect, sync de {datetime.now().strftime('%d/%m/%Y')}"}
html = template.read_text(encoding="utf-8").replace("/*DATA*/", json.dumps(raw, ensure_ascii=False, separators=(",", ":")))
(root / "performance.html").write_text(html, encoding="utf-8")
print(f"Performance Center criado: {len(rows)} corridas, {len(sleep_m)} meses, {len(rec_rows)} dias de recuperação.")
