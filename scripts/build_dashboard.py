from __future__ import annotations
import json
from pathlib import Path

root = Path("output")
activities = json.loads((root / "activities.json").read_text(encoding="utf-8"))["activities"]
details = json.loads((root / "activity_details.json").read_text(encoding="utf-8"))
detail_by_id = {str(x["activity_id"]): x for x in details}
runs = []
for a in activities:
    kind = (a.get("activityType") or {}).get("typeKey", "")
    if kind not in ("running", "treadmill_running"):
        continue
    detail = detail_by_id.get(str(a.get("activityId")), {})
    fit = detail.get("fit", {})
    records = []
    for r in fit.get("records", []):
        if r.get("distance_m") is None:
            continue
        records.append({
            "km": round(r["distance_m"] / 1000, 3),
            "speed": r.get("speed_mps"), "hr": r.get("heart_rate"),
            "alt": r.get("altitude_m"), "lat": r.get("latitude"), "lon": r.get("longitude"),
        })
    runs.append({
        "id": str(a.get("activityId")), "name": a.get("activityName") or "Corrida",
        "date": a.get("startTimeLocal", "")[:16],
        "km": round((a.get("distance") or 0) / 1000, 2),
        "duration": round(a.get("duration") or 0),
        "hr": a.get("averageHR"), "maxHr": a.get("maxHR"),
        "load": round(a.get("activityTrainingLoad") or 0),
        "records": records, "laps": fit.get("laps", []),
        "fit_error": detail.get("fit_error"),
    })
data = json.dumps(runs, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>Garmin FIT Detail</title>
<style>
:root{--bg:#091120;--p:#14213a;--line:#2b3e5e;--txt:#eff5ff;--muted:#9aacc8;--cyan:#50ddd2;--blue:#83aaff;--orange:#ffbd76}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 10% 0%,#1a3155,#091120 55%);color:var(--txt);font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1050px;margin:auto;padding:24px 14px 48px}.eyebrow{color:var(--cyan);font-weight:800;letter-spacing:2px;font-size:11px}h1{font-size:32px;margin:8px 0}.muted{color:var(--muted);font-size:12px}.card{background:var(--p);border:1px solid var(--line);border-radius:16px;padding:16px;margin-top:12px}.row{display:flex;gap:10px;flex-wrap:wrap}.metric{flex:1;min-width:120px;background:#0d192d;border:1px solid var(--line);border-radius:11px;padding:12px}.metric small{color:var(--muted)}.metric b{display:block;font-size:22px;margin-top:5px}select{width:100%;padding:12px;background:#0b172a;color:var(--txt);border:1px solid var(--line);border-radius:10px;font-size:15px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.chart{width:100%;height:230px;display:block}.map{width:100%;height:250px;background:#0b172a;border-radius:10px}.notice{border-left:3px solid var(--orange);padding:10px 12px;background:#2a241b;border-radius:0 8px 8px 0;color:#f1d8b8;font-size:12px;line-height:1.5;margin-top:10px}@media(max-width:720px){.grid{grid-template-columns:1fr}h1{font-size:28px}}
</style></head><body><main><div class="eyebrow">GARMIN CONNECT · FIT DETAIL</div><h1>Análise por atividade</h1><p class="muted">Selecione uma corrida para explorar ritmo, frequência cardíaca, altimetria e rota GPS, quando disponíveis no arquivo FIT.</p>
<div class="card"><label for="activity">Atividade</label><select id="activity"></select><div class="row" id="metrics" style="margin-top:12px"></div><div id="notice"></div></div>
<div class="grid"><section class="card"><h2>Ritmo por distância</h2><svg id="pace" class="chart" viewBox="0 0 640 230"></svg></section><section class="card"><h2>Frequência cardíaca</h2><svg id="hr" class="chart" viewBox="0 0 640 230"></svg></section><section class="card"><h2>Altimetria</h2><svg id="elev" class="chart" viewBox="0 0 640 230"></svg></section><section class="card"><h2>Traçado GPS</h2><svg id="route" class="map" viewBox="0 0 640 250"></svg></section></div>
<section class="card"><h2>Parciais (laps)</h2><div id="laps" class="muted"></div></section>
<footer class="muted" style="margin-top:16px;line-height:1.6">O arquivo FIT pode conter localização precisa. Mantenha este artefato privado e não publique coordenadas em páginas públicas.</footer></main>
<script>
var RUNS=__DATA__;
function el(id){return document.getElementById(id)}
function fmt(n,d){return n==null?"—":Number(n).toLocaleString("pt-BR",{maximumFractionDigits:d||1})}
function pace(s){if(!s||s<=0)return "—";var v=1000/s,m=Math.floor(v/60),r=Math.round(v%60);if(r===60){m++;r=0}return m+":"+String(r).padStart(2,"0")}
function chart(id,records,key,color,formatter){var svg=el(id),arr=records.filter(function(r){return r[key]!=null&&isFinite(Number(r[key]))});if(arr.length<2){svg.innerHTML='<text x="320" y="115" text-anchor="middle" fill="#9aacc8">Dados insuficientes</text>';return}var vals=arr.map(function(r){return Number(r[key])}),min=Math.min.apply(null,vals),max=Math.max.apply(null,vals);if(max===min)max=min+1;var pts=arr.map(function(r){return [45+(r.km/Math.max(1,records[records.length-1].km||1))*580,12+(max-Number(r[key]))/(max-min)*180]});var p=pts.map(function(x){return x.join(",")}).join(" ");svg.innerHTML='<polyline points="'+p+'" fill="none" stroke="'+color+'" stroke-width="2.5" stroke-linejoin="round"/><text x="320" y="222" text-anchor="middle" fill="#9aacc8" font-size="11">Distância (km)</text>'}
function route(records){var pts=records.filter(function(r){return r.lat!=null&&r.lon!=null}),svg=el("route");if(pts.length<2){svg.innerHTML='<text x="320" y="125" text-anchor="middle" fill="#9aacc8">Sem GPS nesta atividade</text>';return}var xs=pts.map(function(p){return p.lon}),ys=pts.map(function(p){return p.lat}),minX=Math.min.apply(null,xs),maxX=Math.max.apply(null,xs),minY=Math.min.apply(null,ys),maxY=Math.max.apply(null,ys);var xy=pts.map(function(p){return [25+(p.lon-minX)/(maxX-minX||1)*590,225-(p.lat-minY)/(maxY-minY||1)*200]});svg.innerHTML='<polyline points="'+xy.map(function(p){return p.join(",")}).join(" ")+'" fill="none" stroke="#50ddd2" stroke-width="3"/>'}
function show(){var a=RUNS.find(function(x){return x.id===el("activity").value});if(!a)return;var r=a.records||[];var items=[["Distância",fmt(a.km,2)+" km"],["Duração",Math.round(a.duration/60)+" min"],["Ritmo médio",pace(a.duration/Math.max(a.km*1000,1))+"/km"],["FC média",a.hr?Math.round(a.hr)+" bpm":"—"],["FC máxima",a.maxHr?a.maxHr+" bpm":"—"],["Carga",a.load]];el("metrics").innerHTML=items.map(function(x){return '<div class="metric"><small>'+x[0]+'</small><b>'+x[1]+'</b></div>'}).join("");el("notice").innerHTML=a.fit_error?'<div class="notice">Falha ao ler FIT: '+String(a.fit_error).slice(0,180)+'</div>':r.length?'<p class="muted">'+r.length+' registros FIT lidos.</p>':'<div class="notice">Sem registros FIT. Os resumos da atividade continuam disponíveis.</div>';chart("pace",r,"speed","#50ddd2",pace);chart("hr",r,"hr","#83aaff",fmt);chart("elev",r,"alt","#ffbd76",fmt);route(r);var laps=a.laps||[];el("laps").innerHTML=laps.length?laps.map(function(l,i){return '<p>Volta '+(i+1)+': '+fmt((l.total_distance||0)/1000,2)+' km · '+fmt(l.total_timer_time/60,1)+' min · FC média '+(l.avg_heart_rate||"—")+'</p>'}).join(""):"Nenhuma volta detalhada retornada."}
el("activity").innerHTML=RUNS.map(function(a){return '<option value="'+a.id+'">'+a.date+" · "+a.name+" · "+fmt(a.km,2)+' km</option>'}).join("");el("activity").addEventListener("change",show);if(RUNS.length)show();
</script></body></html>"""
(root / "dashboard.html").write_text(html.replace("__DATA__", data), encoding="utf-8")
print("Dashboard criado com", len(runs), "atividades.")
