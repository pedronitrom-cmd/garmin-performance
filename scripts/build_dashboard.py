from __future__ import annotations
import json, math, html
from pathlib import Path
from collections import defaultdict
from datetime import datetime

root = Path("output")
activities = json.loads((root / "activities.json").read_text(encoding="utf-8"))["activities"]
details = json.loads((root / "activity_details.json").read_text(encoding="utf-8"))
by_id = {str(x["activity_id"]): x for x in details}

def pace(sec):
    if sec is None or not math.isfinite(sec) or sec <= 0: return "—"
    n=round(sec); return f"{n//60}:{n%60:02d}/km"
def duration(sec):
    if sec is None: return "—"
    n=round(sec); return f"{n//60}:{n%60:02d}"
def chart(records, key, title, unit, convert=lambda x:x, reverse=False):
    pts=[]
    for r in records:
        x=r.get("distance_m"); y=r.get(key)
        if x is None or y is None: continue
        try:
            x=float(x)/1000; y=convert(float(y))
            if math.isfinite(x) and math.isfinite(y): pts.append((x,y))
        except (TypeError,ValueError): pass
    if len(pts)<2: return '<p class="empty">Dados insuficientes nesta atividade.</p>'
    if len(pts)>320: pts=[pts[round(i*(len(pts)-1)/319)] for i in range(320)]
    lo=min(y for _,y in pts); hi=max(y for _,y in pts)
    if hi==lo: hi=lo+1
    xmax=max(x for x,_ in pts) or 1
    W,H,L,R,T,B=760,230,65,12,18,38
    xy=[]
    for x,y in pts:
        px=L+x/xmax*(W-L-R); f=(y-lo)/(hi-lo)
        py=T+(f if reverse else 1-f)*(H-T-B)
        xy.append(f"{px:.1f},{py:.1f}")
    labels=""
    for i in range(5):
        f=i/4; y=hi-(hi-lo)*f if reverse else lo+(hi-lo)*f
        text=pace(y) if unit=="pace" else f"{y:.0f} {unit}"
        yy=T+(H-T-B)*f
        labels+=f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="#2b3e5e"/><text x="4" y="{yy+4:.1f}" fill="#9aacc8" font-size="11">{text}</text>'
    labels+=f'<text x="{W-R-90}" y="{H-8}" fill="#9aacc8" font-size="11">Distância (km)</text>'
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title}">{labels}<polyline points="{" ".join(xy)}" fill="none" stroke="#50ddd2" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'

runs=[]
for a in activities:
    kind=(a.get("activityType") or {}).get("typeKey","")
    if kind not in ("running","treadmill_running"): continue
    d=by_id.get(str(a.get("activityId")),{})
    fit=d.get("fit",{})
    try: dt=datetime.fromisoformat((a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:19].replace("Z",""))
    except ValueError: dt=None
    runs.append({"a":a,"d":d,"fit":fit,"dt":dt})
runs.sort(key=lambda x:x["dt"] or datetime.min, reverse=True)
months=defaultdict(list)
for x in runs:
    key=x["dt"].strftime("%Y-%m") if x["dt"] else "sem-data"
    months[key].append(x)
month_nav=[]
month_sections=[]
total_km=0
for key,items in sorted(months.items(),reverse=True):
    title=datetime.strptime(key,"%Y-%m").strftime("%B %Y") if key!="sem-data" else "Sem data"
    title=title.capitalize()
    km=sum((x["a"].get("distance") or 0)/1000 for x in items); total_km+=km
    month_id="m"+key.replace("-","")
    month_nav.append(f'<a href="#{month_id}">{title} · {km:.1f} km · {len(items)} treinos</a>')
    blocks=[]
    for i,x in enumerate(items,1):
        a=x["a"]; fit=x["fit"]; rec=fit.get("records",[]); laps=fit.get("laps",[])
        dist=(a.get("distance") or 0)/1000; dur=a.get("duration") or 0
        avg_hr=a.get("averageHR"); max_hr=a.get("maxHR")
        name=html.escape(a.get("activityName") or "Corrida")
        date=x["dt"].strftime("%d/%m/%Y %H:%M") if x["dt"] else "Data indisponível"
        laprows=""
        for j,l in enumerate(laps,1):
            ld=(l.get("total_distance") or 0)/1000; lt=l.get("total_timer_time")
            lp=lt/ld if ld and lt else None
            laprows+=f'<tr><td>{j}</td><td>{ld:.2f} km</td><td>{duration(lt)}</td><td>{pace(lp)}</td><td>{round(l.get("avg_heart_rate") or 0) or "—"}</td></tr>'
        if not laprows: laprows='<tr><td colspan="5">Sem voltas no arquivo FIT.</td></tr>'
        blocks.append(f"""
        <article class="activity">
        <div class="date">{date} · {html.escape((a.get("activityType") or {}).get("typeKey",""))}</div><h3>{name}</h3>
        <div class="metrics">
        <div><b>{dist:.2f} km</b><small>Distância</small></div><div><b>{duration(dur)}</b><small>Tempo</small></div>
        <div><b>{pace(dur/dist if dist else None)}</b><small>Ritmo médio</small></div><div><b>{round(avg_hr) if avg_hr else "—"} bpm</b><small>FC média</small></div>
        <div><b>{round(max_hr) if max_hr else "—"} bpm</b><small>FC máxima</small></div><div><b>{len(rec):,}</b><small>Registros FIT</small></div></div>
        <h4>Ritmo por distância</h4>{chart(rec,"speed_mps","Ritmo","pace",lambda v:1000/v if v>0 else float("nan"),True)}
        <h4>Frequência cardíaca</h4>{chart(rec,"heart_rate","Frequência cardíaca","bpm")}
        <h4>Altimetria</h4>{chart(rec,"altitude_m","Altimetria","m")}
        <details><summary>Voltas e parciais ({len(laps)})</summary><div class="scroll"><table><thead><tr><th>#</th><th>Distância</th><th>Tempo</th><th>Ritmo</th><th>FC média</th></tr></thead><tbody>{laprows}</tbody></table></div></details>
        </article>""")
    month_sections.append(f'<section id="{month_id}" class="month"><div class="kicker">HISTÓRICO MENSAL</div><h2>{title}</h2><p class="monthstat">{km:.1f} km · {len(items)} sessões · média {km/max(1,len(items)):.1f} km por sessão</p>{"".join(blocks)}<a class="top" href="#top">↑ Voltar ao início</a></section>')


# Wellness: daily summaries are the most complete source for recovery metrics.
wellness_path = root / "wellness.json"
wellness_panel = ""
if wellness_path.exists():
    wellness = json.loads(wellness_path.read_text(encoding="utf-8"))
    datasets = wellness.get("datasets", {})
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
                    for value in data.values():
                        if isinstance(value, list):
                            out.extend(value)
        return out
    sleep_rows = {x.get("calendarDate"): x for x in flatten("sleep_summaries") if x.get("calendarDate")}
    hrv_rows = {x.get("calendarDate"): x for x in flatten("hrv_summaries", "hrvSummaries") if x.get("calendarDate")}
    daily_rows = {x.get("calendarDate"): x for x in flatten("daily_summaries", "data") if x.get("calendarDate")}
    def avg(vals):
        vals = [float(v) for v in vals if isinstance(v, (int,float)) and math.isfinite(v)]
        return sum(vals)/len(vals) if vals else None
    sleep_hours = {d: (x.get("sleepTimeSeconds") or 0)/3600 for d,x in sleep_rows.items() if x.get("sleepTimeSeconds")}
    sleep_score = {d: ((x.get("sleepScores") or {}).get("overall") or {}).get("value") for d,x in sleep_rows.items()}
    hrv_avg = {d: x.get("lastNightAvg") for d,x in hrv_rows.items()}
    hrv_week = {d: x.get("weeklyAvg") for d,x in hrv_rows.items()}
    bb = {d: ((x.get("bodyBattery") or {}).get("latestValue")) for d,x in daily_rows.items()}
    stress_avg = {d: ((x.get("stress") or {}).get("avgLevel")) for d,x in daily_rows.items()}
    resting_hr = {d: ((x.get("heartRate") or {}).get("restingValue")) for d,x in daily_rows.items()}
    steps = {d: (((x.get("movement") or {}).get("steps") or {}).get("value")) for d,x in daily_rows.items()}
    spo2 = {d: ((x.get("pulseOx") or {}).get("avgValue")) for d,x in daily_rows.items()}
    resp = {d: ((x.get("respiration") or {}).get("avgValue")) for d,x in daily_rows.items()}
    dates = sorted(set(sleep_rows)|set(hrv_rows)|set(daily_rows))
    def latest(mapping):
        valid = [(d,v) for d,v in mapping.items() if isinstance(v,(int,float))]
        return max(valid) if valid else (None,None)
    def metric(label, mapping, unit="", digits=0):
        d,v=latest(mapping)
        value = f"{v:.{digits}f}{unit}" if v is not None else "—"
        when = d if d else "sem registro"
        return f'<div><b>{value}</b><small>{label} · {when}</small></div>'
    wellness_months = defaultdict(list)
    for d in dates:
        wellness_months[d[:7]].append(d)
    month_rows=[]
    for m,ds in sorted(wellness_months.items(), reverse=True):
        month_rows.append(f'<tr><td>{m}</td><td>{avg([sleep_hours.get(d) for d in ds]):.1f} h</td><td>{avg([sleep_score.get(d) for d in ds]):.0f}</td><td>{avg([hrv_avg.get(d) for d in ds]):.0f} ms</td><td>{avg([bb.get(d) for d in ds]):.0f}</td><td>{avg([stress_avg.get(d) for d in ds]):.0f}</td><td>{avg([resting_hr.get(d) for d in ds]):.0f}</td></tr>')
    # Link each run to same-day recovery measurements (sleep ending that morning).
    run_recovery_rows = []
    for item in runs[:40]:
        activity = item["a"]
        day = item["dt"].strftime("%Y-%m-%d") if item["dt"] else None
        if not day: continue
        distance_km = (activity.get("distance") or 0)/1000
        elapsed = activity.get("duration") or 0
        run_pace = elapsed/distance_km if distance_km else None
        pace_label = pace(run_pace)
        hr_label = f'{round(activity.get("averageHR"))} bpm' if activity.get("averageHR") else "—"
        score = sleep_score.get(day)
        hrv_value = hrv_avg.get(day)
        bb_value = bb.get(day)
        run_recovery_rows.append(
            f'<tr><td>{day}</td><td>{distance_km:.1f} km</td><td>{pace_label}</td><td>{hr_label}</td>'
            f'<td>{round(score) if isinstance(score,(int,float)) else "—"}</td>'
            f'<td>{round(hrv_value) if isinstance(hrv_value,(int,float)) else "—"}</td>'
            f'<td>{round(bb_value) if isinstance(bb_value,(int,float)) else "—"}</td></tr>'
        )
    wellness_panel = f"""
    <section class="panel" id="recovery">
      <div class="kicker">RECUPERAÇÃO · SAÚDE DIÁRIA</div><h2>Sono, VFC e recuperação</h2>
      <p>Dados diários encontrados: {len(daily_rows)} resumos · {len(sleep_rows)} noites de sono · {len(hrv_rows)} registros de VFC. Valores recentes são mostrados com a data correspondente; médias mensais usam apenas dias com medição.</p>
      <div class="metrics">
      {metric("Sono mais recente",sleep_hours," h",1)}
      {metric("Pontuação do sono",sleep_score,"",0)}
      {metric("VFC noturna",hrv_avg," ms",0)}
      {metric("VFC média semanal",hrv_week," ms",0)}
      {metric("Body Battery",bb,"",0)}
      {metric("Estresse médio diário",stress_avg,"",0)}
      {metric("FC repouso",resting_hr," bpm",0)}
      {metric("Passos",steps,"",0)}
      {metric("SpO₂ média",spo2,"%",0)}
      {metric("Respiração média",resp," rpm",1)}
      </div>
      <h3>Treinos x recuperação</h3><p>Comparação das corridas recentes com sono, VFC e Body Battery registrados na mesma data. É uma associação exploratória, não prova de causalidade.</p><div class="scroll"><table><thead><tr><th>Data</th><th>Distância</th><th>Ritmo</th><th>FC média</th><th>Score sono</th><th>VFC</th><th>Body Battery</th></tr></thead><tbody>{''.join(run_recovery_rows) or '<tr><td colspan="7">Sem dados suficientes para cruzamento.</td></tr>'}</tbody></table></div>
      <h3>Evolução mensal</h3><div class="scroll"><table><thead><tr><th>Mês</th><th>Sono</th><th>Score</th><th>VFC</th><th>Body Battery</th><th>Estresse</th><th>FC repouso</th></tr></thead><tbody>{''.join(month_rows)}</tbody></table></div>
      <p class="date">Body Battery, estresse, passos, FC de repouso, SpO₂ e respiração são extraídos dos resumos diários. Consultas específicas de estresse/passos podem falhar sem significar ausência de dados. Não há estimativas para dias sem medição.</p>
    </section>
    """

html_doc=f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>Garmin Performance Pro</title>
<style>
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#091120;color:#eff5ff;font:15px -apple-system,BlinkMacSystemFont,Arial,sans-serif;line-height:1.5}}main{{max-width:1000px;margin:auto;padding:18px}}h1{{font-size:34px;line-height:1.1}}h2{{font-size:25px}}h3{{font-size:20px;margin:8px 0}}h4{{font-size:16px;margin:20px 0 8px}}p,.date,small{{color:#9aacc8}}.kicker{{color:#50ddd2;font-size:11px;font-weight:800;letter-spacing:2px}}.panel,.activity,.month{{background:#14213a;border:1px solid #2b3e5e;border-radius:18px;padding:17px;margin:16px 0}}.metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:14px 0}}.metrics div{{background:#0d192d;border-radius:11px;padding:11px}}.metrics b{{display:block;font-size:20px}}.metrics small{{font-size:11px}}svg{{display:block;width:100%;height:auto;background:#0b172a;border-radius:12px}}.monthnav a{{display:block;color:#b9d9ff;text-decoration:none;padding:10px 0;border-bottom:1px solid #2b3e5e}}.monthstat{{color:#50ddd2;font-weight:700}}body:has(.month:target) .month:not(:target){{display:none}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:480px;font-size:12px}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #2b3e5e}}th{{color:#50ddd2}}details{{background:#0d192d;border-radius:10px;padding:12px;margin-top:14px}}summary{{color:#b9d9ff;font-weight:700}}.empty{{background:#0d192d;padding:15px;border-radius:10px;color:#9aacc8}}.top{{display:inline-block;margin-top:12px;color:#9aacc8}}@media(min-width:700px){{main{{padding:28px}}.metrics{{grid-template-columns:repeat(3,minmax(0,1fr))}}.panel,.activity,.month{{padding:22px}}}}
</style></head><body><main id="top"><div class="kicker">GARMIN CONNECT · PERFORMANCE PRO</div><h1>Painel de corrida</h1>
<p>Histórico: {min((x["dt"] for x in runs if x["dt"]),default=datetime.now()).strftime("%d/%m/%Y")} a {max((x["dt"] for x in runs if x["dt"]),default=datetime.now()).strftime("%d/%m/%Y")} · {len(runs)} corridas/esteira · {total_km:.1f} km.</p>
<section class="panel"><div class="kicker">FILTRO POR MÊS</div><p>Escolha um mês para ir diretamente às atividades daquele período. Os valores de distância aparecem acima dos gráficos e os dados de cada treino estão identificados.</p><nav class="monthnav">{"".join(month_nav)}</nav></section>
{wellness_panel}
{"".join(month_sections)}
<footer class="panel"><p>Relatório pessoal gerado a partir dos dados FIT do Garmin Connect. Métricas ausentes não são estimadas. Mantenha este arquivo privado, pois pode conter traçados GPS.</p></footer>
</main></body></html>'''
(root/"dashboard.html").write_text(html_doc,encoding="utf-8")
print(f"Dashboard mensal estático criado: {len(runs)} corridas em {len(months)} meses.")



# Advanced training analysis (static HTML; iPhone/Safari friendly).
from statistics import mean as _mean, median as _median, pstdev as _pstdev, correlation as _correlation
from datetime import timedelta as _td
def _v(xs):
    z=[float(v) for v in xs if isinstance(v,(int,float)) and math.isfinite(v)]
    return sum(z)/len(z) if z else None
def _p(sec):
    if not sec:return "—"
    n=round(sec);return f"{n//60}:{n%60:02d}"
def _kind(x):
    n=(x["a"].get("activityName") or "").lower()
    if any(t in n for t in ("prova","race","competição")): return "Prova"
    if any(t in n for t in ("interval","tiro","repetição")): return "Intervalado"
    if any(t in n for t in ("limiar","tempo run","threshold")): return "Limiar/tempo"
    if "long" in n or "longo" in n or (x["a"].get("distance") or 0)>=15000: return "Longão"
    return "Rodagem/outro"
valid=[x for x in runs if x["dt"] and (x["a"].get("distance") or 0)>=1000]
last_dt=max(x["dt"] for x in valid)
km7=sum((x["a"].get("distance") or 0)/1000 for x in valid if x["dt"]>=last_dt-_td(days=6))
km28=sum((x["a"].get("distance") or 0)/1000 for x in valid if x["dt"]>=last_dt-_td(days=27))
load7=sum(x["a"].get("activityTrainingLoad") or 0 for x in valid if x["dt"]>=last_dt-_td(days=6))
load28=sum(x["a"].get("activityTrainingLoad") or 0 for x in valid if x["dt"]>=last_dt-_td(days=27))
wkavg=km28/4
ratio=km7/wkavg if wkavg else None
quality14=[x for x in valid if x["dt"]>=last_dt-_td(days=13) and _kind(x) in ("Intervalado","Limiar/tempo","Prova")]
recent21=sorted([x for x in valid if x["dt"]>=last_dt-_td(days=20)],key=lambda x:x["dt"],reverse=True)
session_html="".join(
 f'<tr><td>{x["dt"].strftime("%d/%m %H:%M")}</td><td>{html.escape(x["a"].get("activityName") or "Corrida")}</td><td>{_kind(x)}</td><td>{(x["a"].get("distance") or 0)/1000:.1f}</td><td>{_p((x["a"].get("duration") or 0)/((x["a"].get("distance") or 1)/1000))}</td><td>{x["a"].get("averageHR") or "—"}</td><td>{(x["a"].get("activityTrainingLoad") or 0):.0f}</td></tr>'
 for x in recent21)
month_rows=[]
for m,xs in sorted(months.items()):
    km=sum((x["a"].get("distance") or 0)/1000 for x in xs)
    month_rows.append((m,len(xs),km,_v([x["a"].get("averageHR") for x in xs]),_v([x["a"].get("avgPower") for x in xs]),sum(x["a"].get("activityTrainingLoad") or 0 for x in xs)))
monthly_html="".join(f'<tr><td>{m}</td><td>{n}</td><td>{km:.1f}</td><td>{hr:.0f}</td><td>{pw:.0f}</td><td>{ld:.0f}</td></tr>' for m,n,km,hr,pw,ld in month_rows[-18:][::-1])
def _best(lo,hi):
    z=[x for x in valid if lo<=(x["a"].get("distance") or 0)/1000<=hi]
    if not z:return "<tr><td colspan=4>Sem atividade na faixa</td></tr>"
    x=min(z,key=lambda q:(q["a"].get("duration") or 1)/((q["a"].get("distance") or 1)/1000))
    d=x["a"].get("distance")/1000; sec=x["a"].get("duration")/d
    return f'<tr><td>{x["dt"].strftime("%d/%m/%Y")}</td><td>{d:.2f} km</td><td>{_p(sec)}/km</td><td>{html.escape(x["a"].get("activityName") or "Corrida")}</td></tr>'
# Simple monthly volume sparkline as inline SVG.
pts=[(m,km) for m,n,km,hr,pw,ld in month_rows[-18:]]
if len(pts)>1:
    ys=[v for _,v in pts];lo,hi=min(ys),max(ys);hi=hi if hi>lo else lo+1
    xy=" ".join(f'{48+i*660/(len(pts)-1):.1f},{180-(v-lo)/(hi-lo)*145:.1f}' for i,(_,v) in enumerate(pts))
    vol_svg=f'<svg viewBox="0 0 760 205" role="img" aria-label="Volume mensal"><polyline points="{xy}" fill="none" stroke="#50ddd2" stroke-width="3"/></svg>'
else: vol_svg="<p>Dados insuficientes</p>"
analysis_html=f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>Garmin · Análise avançada</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#08111f;color:#edf4ff;font:15px -apple-system,BlinkMacSystemFont,Arial,sans-serif;line-height:1.5}}main{{max-width:1000px;margin:auto;padding:18px}}h1{{font-size:32px}}h2{{font-size:23px}}h3{{font-size:17px}}p,small{{color:#9eb0ca}}.panel{{background:#121f35;border:1px solid #263b59;border-radius:17px;padding:17px;margin:16px 0}}.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}.card{{background:#0c192b;border-radius:12px;padding:12px}}.card b{{display:block;font-size:23px}}.card small{{font-size:11px}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:600px;font-size:12px}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #263b59;white-space:nowrap}}th{{color:#50ddd2}}svg{{width:100%;height:auto}}svg polyline{{fill:none;stroke:#50ddd2;stroke-width:3}}.tag{{color:#50ddd2;font-size:11px;letter-spacing:2px;font-weight:800}}.call{{background:#0c192b;border-left:3px solid #50ddd2;padding:12px;margin:10px 0}}.warn{{border-color:#ffbd70}}@media(min-width:700px){{main{{padding:28px}}.cards{{grid-template-columns:repeat(4,1fr)}}}}</style></head><body><main>
<div class="tag">GARMIN CONNECT · PERFORMANCE LAB</div><h1>Análise avançada de corrida</h1><p>Atualizado em {last_dt.strftime("%d/%m/%Y")} · {len(valid)} atividades de corrida com distância válida.</p>
<section class="panel"><div class="tag">01 · VISÃO GERAL</div><h2>Volume, frequência e carga</h2><div class="cards">
<div class="card"><small>Volume histórico</small><b>{sum((x["a"].get("distance") or 0)/1000 for x in valid):,.0f} km</b><small>Desde {min(x["dt"] for x in valid).strftime("%d/%m/%Y")}</small></div>
<div class="card"><small>Tempo correndo</small><b>{sum(x["a"].get("duration") or 0 for x in valid)/3600:.1f} h</b><small>Tempo registrado</small></div>
<div class="card"><small>Últimos 7 dias</small><b>{km7:.1f} km</b><small>{sum(1 for x in valid if x["dt"]>=last_dt-_td(days=6))} sessões · carga {load7:.0f}</small></div>
<div class="card"><small>Últimos 28 dias</small><b>{km28:.1f} km</b><small>{wkavg:.1f} km/semana · carga {load28:.0f}</small></div></div>
<div class="call {"warn" if ratio and ratio>1.25 else ""}">Razão simples volume 7 dias / média semanal dos últimos 28 dias: <b>{ratio:.2f}×</b>. É um indicador descritivo, não um modelo clínico de lesão. Não use isoladamente para decidir a carga.</div>
</section>
<section class="panel"><div class="tag">02 · EVOLUÇÃO</div><h2>Volume mensal</h2>{vol_svg}<div class="scroll"><table><thead><tr><th>Mês</th><th>Sessões</th><th>Km</th><th>FC média</th><th>Potência média</th><th>Carga Garmin</th></tr></thead><tbody>{monthly_html}</tbody></table></div></section>
<section class="panel"><div class="tag">03 · MELHORES ESFORÇOS</div><h2>Comparação por distância</h2><p>Melhor atividade dentro da faixa de distância, usando duração e distância GPS; não substitui resultado oficial medido.</p><div class="scroll"><table><thead><tr><th>Data</th><th>Distância</th><th>Ritmo</th><th>Atividade</th></tr></thead><tbody>{_best(4.8,5.3)}{_best(9.8,10.3)}{_best(20.8,21.4)}{_best(41,43)}</tbody></table></div></section>
<section class="panel"><div class="tag">04 · TREINOS E DISTRIBUIÇÃO</div><h2>Últimas sessões · 21 dias</h2><div class="scroll"><table><thead><tr><th>Data</th><th>Treino</th><th>Tipo estimado</th><th>Km</th><th>Ritmo</th><th>FC</th><th>Carga</th></tr></thead><tbody>{session_html}</tbody></table></div><div class="call {"warn" if len(quality14)>=3 else ""}">Foram identificadas <b>{len(quality14)}</b> sessões nomeadas como intervalado, limiar/tempo ou prova nos últimos 14 dias. A classificação usa o nome da atividade e precisa ser conferida. Procure espaçar estímulos intensos com recuperação suficiente.</div></section>
<section class="panel"><div class="tag">05 · COMO EVOLUIR</div><h2>Leitura prática</h2><ul><li>Compare treinos equivalentes: percurso, distância, horário, clima e tipo de sessão. Observe pace junto com FC, potência e percepção de esforço.</li><li>Deixe a maior parte do volume em intensidade confortável; evite transformar toda rodagem em ritmo moderado.</li><li>Não aumente volume e intensidade ao mesmo tempo. A progressão deve considerar recuperação, sono e resposta das pernas.</li><li>Nos longões, observe a evolução do ritmo e da FC por blocos; queda acentuada de ritmo ou aumento desproporcional da FC pode sinalizar fadiga, calor ou pacing inadequado.</li><li>Não persiga cadência ou passada como números isolados. Use dinâmica de corrida apenas em sessões comparáveis.</li></ul><div class="call warn">Se houver dor localizada crescente, inchaço, perda de força ou mudança na passada, interrompa a sessão e procure avaliação profissional.</div><p>Limitações: ritmo calculado com duração e GPS; tipos de treino inferidos pelo nome; carga Garmin não é diagnóstico; métricas dependem do relógio/sensor e das condições externas.</p></section>
<footer><p>Arquivo estático otimizado para iPhone. Dados pessoais de treino e possivelmente GPS: mantenha privado.</p></footer></main></body></html>"""
(root/"analysis.html").write_text(analysis_html,encoding="utf-8")
print(f"Análise avançada criada: {len(valid)} atividades válidas, {len(month_rows)} meses e {len(quality14)} sessões de qualidade estimadas.")
