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



# ---------- métricas extras (biomecânica, clima, terreno, carga) ----------
def first(d, *keys):
    for k_ in keys:
        v = (d or {}).get(k_)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return v
    return None


def med(v):
    v = sorted(x for x in v if x is not None)
    return v[len(v) // 2] if v else None


def minetti(g):
    g = max(-0.3, min(0.3, g))
    c = 155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3 + 46.3 * g**2 + 19.5 * g + 3.6
    return max(0.5, c / 3.6)


def run_extras(a, fit, dist_m, dur):
    """Resumo compacto por corrida. Só inclui o que existe; nada é inventado."""
    sess = (fit.get("sessions") or [{}])[0] if fit else {}
    x = {}

    def put(key, val, nd=1):
        if val is not None:
            x[key] = round(val, nd)

    cad = first(a, "averageRunningCadenceInStepsPerMinute", "avgRunCadence")
    if cad is None:
        c = first(sess, "avg_running_cadence", "avg_cadence")
        cad = c * 2 if c is not None and c < 130 else c
    put("cad", cad, 0)
    st = first(a, "avgStrideLength")
    if st is None:
        mm = first(sess, "avg_step_length")
        st = mm / 10 if mm is not None else None
    put("stride", st, 0)
    gct = first(a, "avgGroundContactTime") or first(sess, "avg_stance_time")
    put("gct", gct, 0)
    vo = first(a, "avgVerticalOscillation")
    if vo is None:
        mm = first(sess, "avg_vertical_oscillation")
        vo = mm / 10 if mm is not None else None
    put("vo", vo, 1)
    put("vr", first(a, "avgVerticalRatio") or first(sess, "avg_vertical_ratio"), 1)
    put("pw", first(a, "avgPower") or first(sess, "avg_power"), 0)
    put("np", first(a, "normPower") or first(sess, "normalized_power"), 0)
    put("up", first(a, "elevationGain") if first(a, "elevationGain") is not None else first(sess, "total_ascent"), 0)
    put("dn", first(a, "elevationLoss") if first(a, "elevationLoss") is not None else first(sess, "total_descent"), 0)
    put("te", first(a, "aerobicTrainingEffect") or first(sess, "total_training_effect"), 1)
    put("ta", first(a, "anaerobicTrainingEffect") or first(sess, "total_anaerobic_training_effect"), 1)
    put("ld", first(a, "activityTrainingLoad"), 0)
    put("v2", first(a, "vO2MaxValue"), 0)
    put("cal", first(a, "calories"), 0)

    recs = (fit or {}).get("records") or []
    if recs:
        temps = [r.get("temperature_c") for r in recs if isinstance(r.get("temperature_c"), (int, float))]
        if temps:
            put("tp", sum(temps) / len(temps), 1)
            put("tx", max(temps), 0)
        elif first(a, "minTemperature") is not None:
            put("tp", (first(a, "minTemperature") + (first(a, "maxTemperature") or first(a, "minTemperature"))) / 2, 1)
        pts = [(r["distance_m"], r.get("altitude_m"), r.get("cadence_spm"), r.get("stance_time_ms"), r.get("vertical_oscillation_mm"),
                r.get("speed_mps"))
               for r in recs if isinstance(r.get("distance_m"), (int, float))]
        if len(pts) > 30:
            total = pts[-1][0]
            # terço inicial x terço final (cadência, contato, ritmo)
            def part(lo, hi):
                seg = [p for p in pts if lo * total <= p[0] <= hi * total]
                cads = [p[2] for p in seg if isinstance(p[2], (int, float)) and p[2] > 0]
                gcts = [p[3] for p in seg if isinstance(p[3], (int, float)) and p[3] > 0]
                spd = [p[5] for p in seg if isinstance(p[5], (int, float)) and p[5] > 0.5]
                return med(cads), med(gcts), (1000 / (sum(spd) / len(spd)) if spd else None)
            c1, g1, p1 = part(0.05, 0.33)
            c3, g3, p3 = part(0.67, 1.0)
            if c1 and c3 and (c1 < 130 or c3 < 130) and "cad" in x and x["cad"] > 2 * max(c1, c3) * .8:
                c1, c3 = c1 * 2, c3 * 2
            if c1 and c3:
                put("c1", c1, 0)
                put("c3", c3, 0)
            if g1 and g3:
                put("g1", g1, 0)
                put("g3", g3, 0)
            # ritmo ajustado à inclinação (GAP): segmentos de ~100 m, altitude suavizada
            alts = [(p[0], p[1]) for p in pts if isinstance(p[1], (int, float))]
            if len(alts) > 30 and total > 1500:
                step, grid, i = 100.0, [], 0
                d = 0.0
                while d <= total:
                    while i + 1 < len(alts) and alts[i + 1][0] < d:
                        i += 1
                    grid.append(alts[i][1])
                    d += step
                sm = [sum(grid[max(0, j - 2):j + 3]) / len(grid[max(0, j - 2):j + 3]) for j in range(len(grid))]
                eq = sum(step * minetti((sm[j + 1] - sm[j]) / step) for j in range(len(sm) - 1))
                flat_d = step * (len(sm) - 1)
                if eq > 0 and dur and flat_d > 1000:
                    put("gap", dur / (eq / 1000) , 0)
                    up = sum(max(0, sm[j + 1] - sm[j]) for j in range(len(sm) - 1))
                    if "up" not in x:
                        put("up", up, 0)
    elif first(a, "minTemperature") is not None:
        put("tp", (first(a, "minTemperature") + (first(a, "maxTemperature") or first(a, "minTemperature"))) / 2, 1)
    return x


# ---------- atividades ----------
rows = []
extras = {}
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
    ex = run_extras(a, fit, dist_m, dur)
    if ex:
        extras[dt.strftime("%Y-%m-%d %H:%M")] = ex
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
wellness_extra = {}
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


    # extras de bem-estar: sono por fases, estresse, passos, SpO2, respiração
    wd = []
    for d_ in days:
        x_ = sl.get(d_) or {}
        deep = first(x_, "deepSleepSeconds")
        rem = first(x_, "remSleepSeconds")
        lig = first(x_, "lightSleepSeconds")
        awk = first(x_, "awakeSleepSeconds")
        row = [d_,
               round(deep / 3600, 2) if deep is not None else None, round(rem / 3600, 2) if rem is not None else None,
               round(lig / 3600, 2) if lig is not None else None, round(awk / 3600, 2) if awk is not None else None,
               st.get(d_), stp.get(d_), sp.get(d_), rs.get(d_)]
        if any(v is not None for v in row[1:]):
            wd.append(row)
    wellness_extra["d"] = wd

    # peso: leitura tolerante; mantém a data da última medição
    wt = []
    for it in flatten("weight_measurements", "weight") + flatten("weight_measurements", "dateWeightList"):
        if not isinstance(it, dict):
            continue
        g = first(it, "weight", "weightInGrams", "weightGrams")
        if g is None:
            continue
        kg = g / 1000 if g > 400 else g
        dd = it.get("calendarDate") or str(it.get("measurementTimeLocal") or it.get("date") or it.get("timestampGMT") or "")[:10]
        if len(dd) >= 10 and 25 < kg < 250:
            wt.append([dd[:10], round(kg, 1), first(it, "bodyFat", "bodyFatPercentage"), first(it, "bodyWater", "bodyWaterPercentage"),
                       first(it, "muscleMass", "muscleMassInGrams"), first(it, "bmi")])
    wellness_extra["w"] = sorted({r[0]: r for r in wt}.values())

    def latest(m):
        v = [(d, x) for d, x in m.items() if isinstance(x, (int, float))]
        return max(v) if v else (None, None)

    ds_, sv = latest(sh)
    k = {
        "sono": f"{sv:.1f} h" if sv is not None else "—", "score": latest(ss)[1], "vfc": latest(hrv)[1],
        "vfc7": latest(hrv7)[1], "bb": latest(bb)[1], "estresse": latest(st)[1], "fcr": latest(rhr)[1],
        "passos": latest(stp)[1], "spo2": latest(sp)[1], "resp": latest(rs)[1], "data": ds_ or max(days, default=None),
    }

raw = {"a": rows, "m": sleep_m, "r": rec_rows, "k": k, "x": extras, "we": wellness_extra,
       "src": f"Garmin Connect, sync de {datetime.now().strftime('%d/%m/%Y')}"}
html = template.read_text(encoding="utf-8").replace("/*DATA*/", json.dumps(raw, ensure_ascii=False, separators=(",", ":")))
(root / "performance.html").write_text(html, encoding="utf-8")
census = defaultdict(int)
for ex_ in extras.values():
    for key_ in ex_:
        census[key_] += 1
print(f"Métricas extras em {len(extras)} de {len(rows)} corridas: " + ", ".join(f"{k_}={v_}" for k_, v_ in sorted(census.items())))
print(f"Bem-estar extra: {len(wellness_extra.get('d', []))} dias; peso: {len(wellness_extra.get('w', []))} medições.")
print(f"Performance Center criado: {len(rows)} corridas, {len(sleep_m)} meses, {len(rec_rows)} dias de recuperação.")
