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

html_doc=f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>Garmin Performance Pro</title>
<style>
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#091120;color:#eff5ff;font:15px -apple-system,BlinkMacSystemFont,Arial,sans-serif;line-height:1.5}}main{{max-width:1000px;margin:auto;padding:18px}}h1{{font-size:34px;line-height:1.1}}h2{{font-size:25px}}h3{{font-size:20px;margin:8px 0}}h4{{font-size:16px;margin:20px 0 8px}}p,.date,small{{color:#9aacc8}}.kicker{{color:#50ddd2;font-size:11px;font-weight:800;letter-spacing:2px}}.panel,.activity,.month{{background:#14213a;border:1px solid #2b3e5e;border-radius:18px;padding:17px;margin:16px 0}}.metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:14px 0}}.metrics div{{background:#0d192d;border-radius:11px;padding:11px}}.metrics b{{display:block;font-size:20px}}.metrics small{{font-size:11px}}svg{{display:block;width:100%;height:auto;background:#0b172a;border-radius:12px}}.monthnav a{{display:block;color:#b9d9ff;text-decoration:none;padding:10px 0;border-bottom:1px solid #2b3e5e}}.monthstat{{color:#50ddd2;font-weight:700}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:480px;font-size:12px}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #2b3e5e}}th{{color:#50ddd2}}details{{background:#0d192d;border-radius:10px;padding:12px;margin-top:14px}}summary{{color:#b9d9ff;font-weight:700}}.empty{{background:#0d192d;padding:15px;border-radius:10px;color:#9aacc8}}.top{{display:inline-block;margin-top:12px;color:#9aacc8}}@media(min-width:700px){{main{{padding:28px}}.metrics{{grid-template-columns:repeat(3,minmax(0,1fr))}}.panel,.activity,.month{{padding:22px}}}}
</style></head><body><main id="top"><div class="kicker">GARMIN CONNECT · PERFORMANCE PRO</div><h1>Painel de corrida</h1>
<p>Histórico: {min((x["dt"] for x in runs if x["dt"]),default=datetime.now()).strftime("%d/%m/%Y")} a {max((x["dt"] for x in runs if x["dt"]),default=datetime.now()).strftime("%d/%m/%Y")} · {len(runs)} corridas/esteira · {total_km:.1f} km.</p>
<section class="panel"><div class="kicker">FILTRO POR MÊS</div><p>Escolha um mês para ir diretamente às atividades daquele período. Os valores de distância aparecem acima dos gráficos e os dados de cada treino estão identificados.</p><nav class="monthnav">{"".join(month_nav)}</nav></section>
{"".join(month_sections)}
<footer class="panel"><p>Relatório pessoal gerado a partir dos dados FIT do Garmin Connect. Métricas ausentes não são estimadas. Mantenha este arquivo privado, pois pode conter traçados GPS.</p></footer>
</main></body></html>'''
(root/"dashboard.html").write_text(html_doc,encoding="utf-8")
print(f"Dashboard mensal estático criado: {len(runs)} corridas em {len(months)} meses.")
