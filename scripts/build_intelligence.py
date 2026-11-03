from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path("output")
activities_file = ROOT / "activities.json"
details_file = ROOT / "activity_details.json"
if not activities_file.exists() or not details_file.exists():
    raise SystemExit("Missing activities.json or activity_details.json; run sync_garmin.py first.")

payload = json.loads(activities_file.read_text(encoding="utf-8"))
activities = payload.get("activities", [])
details = json.loads(details_file.read_text(encoding="utf-8"))
details_by_id = {str(x.get("activity_id")): x for x in details}

def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

def parse_date(activity):
    raw = activity.get("startTimeLocal") or activity.get("startTimeGMT")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None

def is_run(activity):
    kind = (activity.get("activityType") or {}).get("typeKey", "")
    return kind in ("running", "treadmill_running")

runs = []
for activity in activities:
    if not is_run(activity):
        continue
    dt = parse_date(activity)
    distance = number(activity.get("distance"))
    duration = number(activity.get("duration"))
    hr = number(activity.get("averageHR"))
    load = number(activity.get("activityTrainingLoad"))
    aid = str(activity.get("activityId"))
    detail = details_by_id.get(aid, {})
    fit = detail.get("fit") or {}
    km = distance / 1000 if distance and distance > 0 else None
    pace_sec = duration / km if duration and km else None
    speed = 1000 / pace_sec if pace_sec and pace_sec > 0 else None
    runs.append({
        "id": aid, "date": dt, "name": activity.get("activityName") or "Corrida",
        "km": km, "duration_s": duration, "hr": hr, "max_hr": number(activity.get("maxHR")),
        "load": load, "pace_s": pace_sec, "speed_mps": speed,
        "records": (fit.get("records") or []), "laps": (fit.get("laps") or []), "fit_count": number(fit.get("record_count")) or 0,
        "fit_error": detail.get("fit_error"), "detail_error": detail.get("detail_error"),
        "activity": activity,
    })

runs.sort(key=lambda x: x["date"] or datetime.min)
dated = [x for x in runs if x["date"]]
latest = max((x["date"] for x in dated), default=datetime.now())
cut7 = latest - timedelta(days=6)
cut28 = latest - timedelta(days=27)
cut56 = latest - timedelta(days=55)
last7 = [x for x in dated if x["date"] >= cut7]
last28 = [x for x in dated if x["date"] >= cut28]
prev28 = [x for x in dated if cut56 <= x["date"] < cut28]

def total_km(items):
    return sum(x["km"] or 0 for x in items)

def total_load(items):
    vals = [x["load"] for x in items if x["load"] is not None]
    return sum(vals) if vals else None

def fmt_pace(seconds):
    if not seconds or seconds <= 0:
        return "—"
    n = round(seconds)
    return f"{n // 60}:{n % 60:02d}/km"

def fmt_num(value, digits=1, suffix=""):
    return f"{value:.{digits}f}{suffix}" if value is not None else "—"

def pct_change(current, previous):
    if previous is None or previous == 0 or current is None:
        return None
    return (current / previous - 1) * 100

# Audit: count duplicated IDs in the original payload, not only deduplicated display rows.
ids = [str(a.get("activityId")) for a in activities if a.get("activityId") is not None]
duplicate_count = len(ids) - len(set(ids))
missing_date = sum(1 for x in runs if x["date"] is None)
missing_distance = sum(1 for x in runs if x["km"] is None)
missing_duration = sum(1 for x in runs if x["duration_s"] is None)
missing_hr = sum(1 for x in runs if x["hr"] is None)
fit_available = sum(1 for x in runs if x["fit_count"] > 0)
fit_errors = sum(1 for x in runs if x["fit_error"])
valid_distance_runs = [x for x in runs if x["km"] and x["km"] > 0]
fit_coverage = fit_available / len(runs) * 100 if runs else None

# Weekly volume and training load; weeks are Monday-Sunday.
weeks = defaultdict(list)
for item in dated:
    y, w, _ = item["date"].isocalendar()
    weeks[f"{y}-W{w:02d}"].append(item)
weekly = []
for key, items in sorted(weeks.items()):
    loads = [x["load"] for x in items if x["load"] is not None]
    weekly.append({
        "week": key, "km": round(total_km(items), 2), "sessions": len(items),
        "load": round(sum(loads), 1) if loads else None,
        "load_coverage": len(loads) / len(items) * 100 if items else 0,
    })

# Compare efficiency only for runs >= 3 km with average HR; this is descriptive, not a lab threshold.
def efficiency_sample(items):
    values = []
    for x in items:
        if x["km"] and x["km"] >= 3 and x["speed_mps"] and x["hr"] and x["hr"] > 0:
            values.append(x["speed_mps"] / x["hr"] * 100)
    return values

eff_now = efficiency_sample(last28)
eff_prev = efficiency_sample(prev28)
eff_now_med = median(eff_now) if eff_now else None
eff_prev_med = median(eff_prev) if eff_prev else None
eff_change = pct_change(eff_now_med, eff_prev_med)

# Session classification uses names and distance as hints only; it is not a workout-intent classifier.
def classify(item):
    name = item["name"].lower()
    if any(t in name for t in ("race", "prova", "competição")):
        return "Prova"
    if any(t in name for t in ("interval", "tiro", "repet", "vo2")):
        return "Intervalado"
    if any(t in name for t in ("limiar", "threshold", "tempo run", "tempo")):
        return "Limiar/tempo"
    if "long" in name or "longo" in name or (item["km"] or 0) >= 18:
        return "Longão"
    return "Rodagem/outro"

types = defaultdict(int)
for item in dated:
    types[classify(item)] += 1

# Wellness coverage summary, without assuming absent fields mean zero.
wellness_path = ROOT / "wellness.json"
wellness_counts = {}
wellness_errors = 0
if wellness_path.exists():
    wellness = json.loads(wellness_path.read_text(encoding="utf-8"))
    wellness_errors = len(wellness.get("errors", []))
    for key, chunks in wellness.get("datasets", {}).items():
        rows = 0
        for chunk in chunks:
            data = chunk.get("data")
            if isinstance(data, list):
                rows += len(data)
            elif isinstance(data, dict):
                rows += sum(len(v) for v in data.values() if isinstance(v, list))
        wellness_counts[key] = {"chunks": len(chunks), "rows": rows}


# Recovery trends from Garmin wellness data. Averages use only days with measurements.
recovery = {"as_of": None, "metrics": {}}
if wellness_path.exists():
    wellness = json.loads(wellness_path.read_text(encoding="utf-8"))
    def flatten_wellness(name, list_key=None):
        rows = []
        for chunk in wellness.get("datasets", {}).get(name, []):
            data = chunk.get("data")
            if isinstance(data, list):
                rows.extend(data)
            elif isinstance(data, dict):
                if list_key and isinstance(data.get(list_key), list):
                    rows.extend(data[list_key])
                else:
                    for value in data.values():
                        if isinstance(value, list):
                            rows.extend(value)
        return rows
    sleep_by_date = {x.get("calendarDate"): x for x in flatten_wellness("sleep_summaries") if x.get("calendarDate")}
    hrv_by_date = {x.get("calendarDate"): x for x in flatten_wellness("hrv_summaries", "hrvSummaries") if x.get("calendarDate")}
    daily_by_date = {x.get("calendarDate"): x for x in flatten_wellness("daily_summaries", "data") if x.get("calendarDate")}
    wellness_dates = sorted(set(sleep_by_date) | set(hrv_by_date) | set(daily_by_date))
    recovery["as_of"] = wellness_dates[-1] if wellness_dates else None
    metric_maps = {
        "sleep_hours": {d: number(x.get("sleepTimeSeconds")) / 3600 for d,x in sleep_by_date.items() if number(x.get("sleepTimeSeconds")) is not None},
        "sleep_score": {d: number(((x.get("sleepScores") or {}).get("overall") or {}).get("value")) for d,x in sleep_by_date.items()},
        "hrv_ms": {d: number(x.get("lastNightAvg")) for d,x in hrv_by_date.items()},
        "resting_hr": {d: number(((x.get("heartRate") or {}).get("restingValue"))) for d,x in daily_by_date.items()},
        "body_battery": {d: number(((x.get("bodyBattery") or {}).get("latestValue"))) for d,x in daily_by_date.items()},
        "stress_avg": {d: number(((x.get("stress") or {}).get("avgLevel"))) for d,x in daily_by_date.items() if number(((x.get("stress") or {}).get("avgLevel"))) is not None and number(((x.get("stress") or {}).get("avgLevel"))) >= 0},
    }
    if recovery["as_of"]:
        wellness_latest = date.fromisoformat(recovery["as_of"])
        windows = {
            "last_7_days": (wellness_latest - timedelta(days=6), wellness_latest),
            "last_28_days": (wellness_latest - timedelta(days=27), wellness_latest),
            "previous_28_days": (wellness_latest - timedelta(days=55), wellness_latest - timedelta(days=28)),
        }
        for key, values in metric_maps.items():
            valid = [(date.fromisoformat(d), v) for d,v in values.items() if v is not None]
            latest_value = max(valid, default=(None, None), key=lambda z: z[0])
            item = {"latest_date": latest_value[0].isoformat() if latest_value[0] else None, "latest": latest_value[1]}
            for window_name, (start, end) in windows.items():
                samples = [v for day,v in valid if start <= day <= end]
                item[window_name] = {"average": round(sum(samples)/len(samples), 2) if samples else None, "days": len(samples)}
            current = item["last_28_days"]["average"]
            previous = item["previous_28_days"]["average"]
            item["change_pct"] = pct_change(current, previous)
            recovery["metrics"][key] = item

recovery_labels = {
    "sleep_hours": ("Sono médio", "h", 1),
    "sleep_score": ("Score de sono", "pts", 0),
    "hrv_ms": ("VFC noturna", "ms", 0),
    "resting_hr": ("FC de repouso", "bpm", 0),
    "body_battery": ("Body Battery", "pts", 0),
    "stress_avg": ("Estresse médio", "pts", 0),
}
recovery_rows = ""
for key, (label, unit, digits) in recovery_labels.items():
    item = recovery["metrics"].get(key, {})
    current = item.get("last_28_days", {}).get("average")
    previous = item.get("previous_28_days", {}).get("average")
    latest_value = item.get("latest")
    fmt = lambda v: f"{v:.{digits}f} {unit}" if v is not None else "—"
    change = item.get("change_pct")
    change_text = f"{change:+.1f}%" if change is not None else "—"
    days = item.get("last_28_days", {}).get("days", 0)
    recovery_rows += f'<tr><td>{label}</td><td>{fmt(latest_value)}</td><td>{fmt(current)}</td><td>{fmt(previous)}</td><td>{change_text}</td><td>{days}</td></tr>'
if not recovery_rows:
    recovery_rows = '<tr><td colspan="6">Sem dados de recuperação disponíveis.</td></tr>'

load7 = total_load(last7)
load28 = total_load(last28)
load_prev28 = total_load(prev28)
load_change = pct_change(load28, load_prev28)
distance_change = pct_change(total_km(last28), total_km(prev28))
sessions_7 = len(last7)
sessions_28 = len(last28)
days_28 = sorted({x["date"].date() for x in last28})
active_days = len(days_28)
weekly_distance = [w["km"] for w in weekly[-4:]]
weekly_mean = sum(weekly_distance) / len(weekly_distance) if weekly_distance else 0
weekly_sd = math.sqrt(sum((v-weekly_mean)**2 for v in weekly_distance)/len(weekly_distance)) if weekly_distance else 0
monotony = weekly_mean / weekly_sd if weekly_sd > 0 else None
strain = weekly_mean * monotony if monotony is not None else None

# Split-half efficiency: compare speed/HR between the two halves of eligible FIT runs.
# Only report when both halves have >= 10 valid paired samples and distance progression exists.
def half_efficiency_for(item):
    # Ignore short activities: split-half efficiency on <5 km is too sensitive to warm-up and GPS noise.
    if not item["km"] or item["km"] < 5:
        return None
    recs = item["records"]
    paired = []
    for r in recs:
        hr = number(r.get("heart_rate"))
        speed = number(r.get("speed_mps"))
        dist = number(r.get("distance_m"))
        if hr and speed and hr > 0 and speed > 0 and dist is not None:
            paired.append((dist, hr, speed))
    if len(paired) < 40:
        return None
    mid = (paired[0][0] + paired[-1][0]) / 2
    first = [p for p in paired if p[0] <= mid]
    second = [p for p in paired if p[0] > mid]
    if len(first) < 10 or len(second) < 10:
        return None
    ef1 = median([p[2] / p[1] for p in first])
    ef2 = median([p[2] / p[1] for p in second])
    return (ef2 / ef1 - 1) * 100 if ef1 else None

half_efficiency_samples = []
for item in last28:
    value = half_efficiency_for(item)
    if value is not None:
        half_efficiency_samples.append({"date": item["date"].strftime("%d/%m/%Y"), "name": item["name"], "efficiency_change_pct": round(value, 1), "km": round(item["km"] or 0, 1)})

# Structured interval analysis from FIT laps. Fast segments are detected from lap pace
# and distance; contiguous fast laps are grouped into one work block (e.g. 2x2 km
# recorded as four consecutive 1 km laps). This is descriptive and avoids relying
# only on activity names or whole-session average pace.
def interval_analysis(item):
    if classify(item) != "Intervalado" or not item["laps"]:
        return None
    segments = []
    for index, lap in enumerate(item["laps"]):
        distance = number(lap.get("total_distance"))
        elapsed = number(lap.get("total_timer_time")) or number(lap.get("total_elapsed_time"))
        if not distance or not elapsed or distance < 400 or distance > 1100:
            continue
        pace = elapsed / (distance / 1000)
        if pace > 285 or pace < 150:
            continue
        segments.append({
            "lap": index + 1, "distance_m": round(distance, 1),
            "duration_s": round(elapsed, 1), "pace_s_km": round(pace, 1),
            "avg_hr": number(lap.get("avg_heart_rate")),
            "max_hr": number(lap.get("max_heart_rate")),
            "avg_power": number(lap.get("avg_power")),
            "trigger": lap.get("lap_trigger"),
        })
    if not segments:
        return None
    # Group only consecutive FIT laps. Any recovery/warm-up lap breaks the block.
    blocks = []
    for segment in segments:
        if blocks and segment["lap"] == blocks[-1]["last_lap"] + 1:
            block = blocks[-1]
            block["distance_m"] += segment["distance_m"]
            block["duration_s"] += segment["duration_s"]
            block["last_lap"] = segment["lap"]
            block["segments"] += 1
            if segment["avg_hr"] is not None:
                block["hr_values"].append(segment["avg_hr"])
            if segment["avg_power"] is not None:
                block["power_values"].append(segment["avg_power"])
        else:
            blocks.append({
                "first_lap": segment["lap"], "last_lap": segment["lap"],
                "distance_m": segment["distance_m"], "duration_s": segment["duration_s"],
                "segments": 1,
                "hr_values": [segment["avg_hr"]] if segment["avg_hr"] is not None else [],
                "power_values": [segment["avg_power"]] if segment["avg_power"] is not None else [],
            })
    for block in blocks:
        block["distance_m"] = round(block["distance_m"], 1)
        block["duration_s"] = round(block["duration_s"], 1)
        block["pace_s_km"] = round(block["duration_s"] / (block["distance_m"] / 1000), 1)
        block["avg_hr"] = round(sum(block["hr_values"]) / len(block["hr_values"]), 1) if block["hr_values"] else None
        block["avg_power"] = round(sum(block["power_values"]) / len(block["power_values"]), 1) if block["power_values"] else None
        del block["hr_values"]
        del block["power_values"]
    paces = [x["pace_s_km"] for x in blocks]
    total_distance = sum(x["distance_m"] for x in blocks)
    total_duration = sum(x["duration_s"] for x in blocks)
    # Recovery is the elapsed time in intervening laps between work blocks.
    recoveries = []
    for left, right in zip(blocks, blocks[1:]):
        gap = [lap for i, lap in enumerate(item["laps"], start=1) if left["last_lap"] < i < right["first_lap"]]
        seconds = sum((number(x.get("total_elapsed_time")) or number(x.get("total_timer_time")) or 0) for x in gap)
        if seconds > 0:
            recoveries.append(round(seconds, 1))
    return {
        "date": item["date"].strftime("%Y-%m-%d"), "name": item["name"],
        "activity_id": item["id"], "total_work_km": round(total_distance / 1000, 2),
        "work_duration_s": round(total_duration, 1),
        "average_work_pace_s_km": round(total_duration / (total_distance / 1000), 1),
        "blocks": blocks, "recoveries_s": recoveries,
        "pace_range_s_km": [round(min(paces), 1), round(max(paces), 1)],
        "pace_spread_pct": round((max(paces) / min(paces) - 1) * 100, 1) if len(paces) > 1 and min(paces) > 0 else 0,
    }

interval_sessions = [x for x in (interval_analysis(item) for item in dated) if x]

# Trend interpretation is intentionally conservative and explains missing/weak evidence.
insights = []
if distance_change is not None:
    if distance_change > 15:
        insights.append(("Atenção ao volume", f"O volume dos últimos 28 dias está {distance_change:.1f}% acima dos 28 dias anteriores. Avalie a progressão junto com recuperação e intensidade; não é, isoladamente, um sinal de lesão."))
    elif distance_change < -15:
        insights.append(("Volume em redução", f"O volume dos últimos 28 dias caiu {abs(distance_change):.1f}% frente ao período anterior. Pode ser planejado (taper/recuperação) ou refletir menor consistência; confira o contexto."))
    else:
        insights.append(("Volume relativamente estável", f"A variação de volume entre os dois blocos de 28 dias foi {distance_change:+.1f}%."))
else:
    insights.append(("Histórico insuficiente", "Ainda não há dois blocos completos de 28 dias para comparar volume com segurança."))
if eff_change is not None and len(eff_now) >= 3 and len(eff_prev) >= 3:
    direction = "melhorou" if eff_change > 2 else "caiu" if eff_change < -2 else "ficou estável"
    insights.append(("Eficiência ritmo/FC", f"A mediana descritiva de velocidade por batimento {direction} {abs(eff_change):.1f}% entre os blocos. A comparação é exploratória e depende de percurso, clima, tipo de treino e sensor."))
else:
    insights.append(("Eficiência ritmo/FC", "Amostra insuficiente para uma comparação robusta: são necessários ao menos 3 treinos válidos em cada bloco."))
if load28 is None or load_prev28 is None:
    insights.append(("Carga Garmin", "A carga de treino Garmin não está preenchida em todas as atividades/períodos; a comparação de carga será exibida apenas quando houver cobertura."))
elif load_change is not None:
    insights.append(("Carga Garmin", f"A soma de carga Garmin mudou {load_change:+.1f}% entre os blocos de 28 dias. Interprete junto com volume, intensidade e recuperação."))
if not half_efficiency_samples:
    insights.append(("Variação de eficiência por metade", "Não houve amostra FIT suficiente em corridas de pelo menos 5 km para calcular a variação entre metades."))

def card(label, value, sub=""):
    return f'<article class="card"><div class="label">{html.escape(label)}</div><div class="value">{value}</div><div class="sub">{html.escape(sub)}</div></article>'

def change_label(value):
    return f"{value:+.1f}%" if value is not None else "—"

weekly_rows = "".join(
    f'<tr><td>{html.escape(w["week"])}</td><td>{w["km"]:.1f} km</td><td>{w["sessions"]}</td><td>{fmt_num(w["load"],0)}</td><td>{w["load_coverage"]:.0f}%</td></tr>'
    for w in weekly[-16:][::-1]
) or '<tr><td colspan="5">Sem semanas válidas.</td></tr>'
recent_rows = "".join(
    f'<tr><td>{x["date"].strftime("%d/%m/%Y")}</td><td>{html.escape(x["name"])}</td><td>{html.escape(classify(x))}</td><td>{fmt_num(x["km"],1," km")}</td><td>{fmt_pace(x["pace_s"])}</td><td>{fmt_num(x["hr"],0," bpm")}</td><td>{fmt_num(x["load"],0)}</td><td>{x["fit_count"]:.0f}</td></tr>'
    for x in dated[-30:][::-1]
) or '<tr><td colspan="8">Sem atividades datadas.</td></tr>'
drift_rows = "".join(
    f'<tr><td>{x["date"]}</td><td>{html.escape(x["name"])}</td><td>{x["km"]:.1f} km</td><td>{x["efficiency_change_pct"]:+.1f}%</td></tr>'
    for x in half_efficiency_samples
) or '<tr><td colspan="4">Sem amostras suficientes.</td></tr>'
insight_html = "".join(
    f'<article class="insight"><h3>{html.escape(title)}</h3><p>{html.escape(body)}</p></article>'
    for title, body in insights
)
wellness_rows = "".join(
    f'<tr><td>{html.escape(k)}</td><td>{v["chunks"]}</td><td>{v["rows"]}</td></tr>'
    for k,v in sorted(wellness_counts.items())
) or '<tr><td colspan="3">wellness.json não encontrado ou sem datasets.</td></tr>'

report = {
    "generated_on": date.today().isoformat(),
    "source_period": {"start": payload.get("period_start"), "end": payload.get("period_end")},
    "quality": {
        "activities_total": len(activities), "running_activities": len(runs),
        "duplicate_activity_ids": duplicate_count, "missing_date": missing_date,
        "missing_distance": missing_distance, "missing_duration": missing_duration,
        "missing_average_hr": missing_hr, "fit_available": fit_available,
        "fit_coverage_pct": round(fit_coverage, 1) if fit_coverage is not None else None,
        "fit_errors": fit_errors, "wellness_errors": wellness_errors,
        "wellness_datasets": wellness_counts,
    },
    "periods": {
        "last_7_days": {"km": round(total_km(last7),2), "sessions": sessions_7, "garmin_load": load7},
        "last_28_days": {"km": round(total_km(last28),2), "sessions": sessions_28, "active_days": active_days, "garmin_load": load28},
        "previous_28_days": {"km": round(total_km(prev28),2), "sessions": len(prev28), "garmin_load": load_prev28},
        "distance_change_pct": distance_change, "load_change_pct": load_change,
        "efficiency_change_pct": eff_change,
    },
    "weekly": weekly, "session_types": dict(types), "heart_rate_half_efficiency_samples": half_efficiency_samples, "interval_sessions": interval_sessions, "recovery": recovery,
    "insights": [{"title": t, "text": b} for t,b in insights],
}
(ROOT / "performance_intelligence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

html_doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>Garmin Performance Intelligence</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#08111f;color:#edf4ff;font:15px -apple-system,BlinkMacSystemFont,Arial,sans-serif;line-height:1.55}}main{{max-width:1100px;margin:auto;padding:20px}}h1{{font-size:clamp(30px,6vw,46px);line-height:1.08;margin:8px 0}}h2{{font-size:23px;margin:28px 0 12px}}h3{{font-size:16px;margin:0 0 6px}}p,.sub,.muted{{color:#a8b8d1}}.eyebrow,.label{{color:#5de0d0;font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:18px 0}}.card,.panel,.insight{{background:#13213a;border:1px solid #2b4163;border-radius:16px;padding:15px}}.value{{font-size:clamp(22px,4vw,30px);font-weight:800;margin:5px 0}}.sub{{font-size:12px}}.panel{{margin:16px 0}}.insights{{display:grid;gap:10px}}.insight p{{margin:0}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:650px;font-size:12px}}td,th{{padding:10px 9px;text-align:left;border-bottom:1px solid #2b4163;white-space:nowrap}}th{{color:#5de0d0}}.note{{font-size:12px;color:#a8b8d1}}.pill{{display:inline-block;border:1px solid #426080;border-radius:999px;padding:4px 9px;font-size:11px;color:#bcd3f1}}footer{{margin:24px 0;color:#8194b2;font-size:12px}}@media(min-width:760px){{main{{padding:34px}}.grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}.insights{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body><main>
<div class="eyebrow">GARMIN CONNECT · V10 · PERFORMANCE INTELLIGENCE</div><h1>Inteligência de performance</h1>
<p>Atualizado em {date.today().strftime("%d/%m/%Y")} · Última atividade no conjunto: {latest.strftime("%d/%m/%Y")} · {len(runs)} corridas/esteira consideradas.</p>
<div class="grid">
{card("Volume · 7 dias",fmt_num(total_km(last7),1," km"),f"{sessions_7} sessões")}
{card("Volume · 28 dias",fmt_num(total_km(last28),1," km"),f"{sessions_28} sessões · {active_days} dias ativos")}
{card("Variação de volume",change_label(distance_change),"Últimos 28 dias vs. 28 dias anteriores")}
{card("Carga Garmin · 28 dias",fmt_num(load28,0),"Soma do campo de carga fornecido pelo Garmin")}
{card("Eficiência ritmo/FC",change_label(eff_change),"Mediana velocidade/FC · amostra exploratória")}
{card("Cobertura FIT",fmt_num(fit_coverage,1,"%"),f"{fit_available} de {len(runs)} corridas")}
{card("Monotonia semanal",fmt_num(monotony,2),"Média/desvio do volume nas últimas 4 semanas disponíveis")}
{card("Strain semanal",fmt_num(strain,1),"Volume médio × monotonia; indicador descritivo")}
</div>
<section class="panel"><h2>Recuperação e prontidão · tendências Garmin</h2><p>Último dia com dados: {html.escape(recovery.get("as_of") or "—")}. As médias consideram apenas dias medidos; a variação compara os últimos 28 dias com os 28 anteriores.</p><div class="table-wrap"><table><thead><tr><th>Indicador</th><th>Último valor</th><th>Média 28d</th><th>28d anteriores</th><th>Variação</th><th>Dias</th></tr></thead><tbody>{recovery_rows}</tbody></table></div><p class="note">VFC, sono, Body Battery e estresse são sinais contextuais. Compare tendências individuais, não use um único valor para decidir intensidade ou diagnosticar fadiga.</p></section>
<section><h2>Leitura automática</h2><div class="insights">{insight_html}</div></section>
<section class="panel"><h2>Qualidade e integridade dos dados</h2><p>Auditoria do conjunto recebido. Ausência de um campo não é convertida em zero nem preenchida por estimativa.</p>
<div class="grid">
{card("Atividades no export",str(len(activities)),"Todos os tipos")}
{card("Corridas analisadas",str(len(runs)),"Corrida e esteira")}
{card("IDs duplicados",str(duplicate_count),"Detectados no arquivo bruto")}
{card("Sem data",str(missing_date),"Corridas sem timestamp interpretável")}
{card("Sem distância",str(missing_distance),"Corridas sem distância válida")}
{card("Sem duração",str(missing_duration),"Corridas sem duração válida")}
{card("Sem FC média",str(missing_hr),"Corridas sem FC média")}
{card("Erros de download FIT",str(fit_errors),"Atividades com erro registrado")}
</div>
<div class="pill">Período: {html.escape(str(payload.get("period_start") or "—"))} a {html.escape(str(payload.get("period_end") or "—"))}</div>
</section>
<section><h2>Volume e carga por semana</h2><div class="panel"><div class="table-wrap"><table><thead><tr><th>Semana ISO</th><th>Distância</th><th>Sessões</th><th>Carga Garmin</th><th>Cobertura da carga</th></tr></thead><tbody>{weekly_rows}</tbody></table></div><p class="note">A semana é agrupada de segunda a domingo. Semanas parciais no início/fim do histórico podem ter volume incompleto.</p></div></section>
<section><h2>Variação de eficiência na segunda metade (FIT)</h2><div class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Treino</th><th>Distância</th><th>Variação velocidade/FC · 2ª metade vs. 1ª</th></tr></thead><tbody>{drift_rows}</tbody></table></div><p class="note">Indicador exploratório da mudança de velocidade por batimento entre as metades. Agora só inclui corridas de pelo menos 5 km e FIT com amostra pareada suficiente. Percurso, acelerações, intervalados, pausas e GPS podem distorcer o resultado; valores negativos não significam necessariamente fadiga nem positivos significam melhora fisiológica.</p></div></section>
<section><h2>Intervalados · análise por repetição</h2><div class="panel"><p class="note">Repetições extraídas das voltas FIT. Blocos consecutivos são agrupados para reconhecer, por exemplo, 2 × 2 km registrados como quatro voltas de 1 km. A identificação depende da qualidade das voltas e pode exigir conferência do treino.</p><div class="table-wrap"><table><thead><tr><th>Data</th><th>Treino</th><th>Blocos</th><th>Distância forte</th><th>Ritmo médio forte</th><th>Faixa de ritmo</th><th>Variação entre blocos</th></tr></thead><tbody>{interval_sessions.slice(-12).reverse().map(x => `<tr><td>${x.date}</td><td>${html.escape(x.name)}</td><td>${x.blocks.length}</td><td>${x.total_work_km.toFixed(2)} km</td><td>${fmt_pace(x.average_work_pace_s_km)}</td><td>${fmt_pace(x.pace_range_s_km[0])} – ${fmt_pace(x.pace_range_s_km[1])}</td><td>${x.pace_spread_pct.toFixed(1)}%</td></tr>`).join("") || '<tr><td colspan="7">Sem voltas FIT elegíveis em treinos intervalados.</td></tr>'}</tbody></table></div></div></section>
<section><h2>Tipos de sessão identificados</h2><div class="panel"><div class="table-wrap"><table><thead><tr><th>Categoria</th><th>Sessões</th></tr></thead><tbody>{"".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k,v in sorted(types.items())) or "<tr><td colspan='2'>Sem dados</td></tr>"}</tbody></table></div><p class="note">A classificação usa o nome da atividade e uma regra simples de distância. Confira os rótulos antes de usar para decisões de treino.</p></div></section>
<section><h2>Últimas 30 corridas</h2><div class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Atividade</th><th>Tipo</th><th>Distância</th><th>Ritmo</th><th>FC média</th><th>Carga</th><th>Registros FIT</th></tr></thead><tbody>{recent_rows}</tbody></table></div></div></section>
<section><h2>Cobertura de recuperação</h2><div class="panel"><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Blocos mensais</th><th>Linhas retornadas</th></tr></thead><tbody>{wellness_rows}</tbody></table></div><p class="note">Erros de consultas wellness registrados: {wellness_errors}. A presença de blocos/linhas não garante que todos os dias tenham medições completas.</p></div></section>
<footer>Relatório analítico pessoal. Indicadores de carga, monotonia, strain, eficiência e deriva são descritivos; não diagnosticam lesões nem substituem avaliação profissional. A razão entre carga aguda/crônica não é usada como previsão individual de lesão. Dados ausentes permanecem ausentes. Preserve a privacidade deste arquivo: exportações podem conter dados pessoais e GPS.</footer>
</main></body></html>"""
(ROOT / "intelligence.html").write_text(html_doc, encoding="utf-8")
print(f"Performance Intelligence criado: {len(runs)} corridas, {len(weekly)} semanas, FIT coverage={fit_coverage}.")
