"""
Genere un tableau de bord HTML autonome a partir d'un backtest.

Esthetique : "terminal de trading" sobre et raffine (fond sombre chaud, accent
or, typographie serif Fraunces pour les titres + monospace pour les chiffres).
Graphiques via Chart.js (CDN -> necessite une connexion internet pour s'afficher).
"""
import json
import math
from pathlib import Path


def _san(x):
    """Rend une valeur serialisable en JSON (gere inf/nan)."""
    if x is None or (isinstance(x, float) and (math.isinf(x) or math.isnan(x))):
        return None
    return x


def _pct(v, signed=True):
    if v is None:
        return "—"
    return f"{v*100:+.1f}%" if signed else f"{v*100:.1f}%"


def _cls(v):
    if v is None:
        return "neu"
    return "up" if v > 0 else ("down" if v < 0 else "neu")


def _pf(v):
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return "∞"
    return f"{v:.2f}"


def generate_dashboard(detail, comparison, context, path="dashboard.html"):
    df = detail.df
    m = detail.metrics
    tf = context.get("timeframe", "1d")
    intraday = tf not in ("1d",)
    fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"

    # Echantillonnage pour limiter le poids du graphique
    step = max(1, len(df) // 800)
    sub = df.iloc[::step]
    labels = [d.strftime(fmt) for d in sub.index]
    equity = [round(float(x), 2) for x in sub["equity"]]
    bh = [round(float(x), 2) for x in sub["buy_hold"]]
    dd = [round(float(x) * 100, 2) for x in sub["drawdown"]]

    # Cartes KPI
    cards = [
        ("Rendement total", _pct(m["total_return"]), _cls(m["total_return"])),
        ("Rendement annualise", _pct(m["annual_return"]), _cls(m["annual_return"])),
        ("vs Buy & Hold", _pct(m["buy_hold_return"]), _cls(m["buy_hold_return"])),
        ("Ratio de Sharpe", f"{m['sharpe']:.2f}", _cls(m["sharpe"])),
        ("Ratio de Sortino", f"{m['sortino']:.2f}", _cls(m["sortino"])),
        ("Drawdown max", _pct(m["max_drawdown"], signed=False), "down"),
        ("Profit factor", _pf(m["profit_factor"]), _cls((m["profit_factor"] or 0) - 1)),
        ("Taux de reussite", _pct(m["win_rate"], signed=False), "neu"),
        ("Nb de trades", str(m["n_trades"]), "neu"),
        ("Temps investi", _pct(m["exposure"], signed=False), "neu"),
    ]
    cards_html = "\n".join(
        f'<div class="card"><div class="card-label">{lbl}</div>'
        f'<div class="card-value {c}">{val}</div></div>'
        for lbl, val, c in cards
    )

    # Tableau comparatif
    comp_rows = ""
    comp_chart = []
    for row in comparison:
        nm, cm = row["name"], row["metrics"]
        comp_chart.append({"name": nm, "ret": _san(cm["total_return"] * 100)})
        comp_rows += (
            f'<tr><td class="nm">{nm}</td>'
            f'<td class="{_cls(cm["total_return"])}">{_pct(cm["total_return"])}</td>'
            f'<td class="{_cls(cm["sharpe"])}">{cm["sharpe"]:.2f}</td>'
            f'<td class="down">{_pct(cm["max_drawdown"], signed=False)}</td>'
            f'<td>{_pf(cm["profit_factor"])}</td>'
            f'<td>{_pct(cm["win_rate"], signed=False)}</td>'
            f'<td>{cm["n_trades"]}</td></tr>'
        )

    # Tableau des trades (les 25 derniers)
    badge = {"stop": "b-stop", "objectif": "b-tp", "signal": "b-sig", "ouvert": "b-open"}
    trades_html = ""
    for t in detail.trades[-25:][::-1]:
        et = t["entry_time"].strftime(fmt)
        xt = t["exit_time"].strftime(fmt)
        r = t.get("reason", "signal")
        trades_html += (
            f'<tr><td>{et}</td><td>{xt}</td>'
            f'<td>{t["entry_price"]:.2f}</td><td>{t["exit_price"]:.2f}</td>'
            f'<td class="{_cls(t["pnl"])}">{t["pnl"]*100:+.1f}%</td>'
            f'<td><span class="badge {badge.get(r,"b-sig")}">{r}</span></td></tr>'
        )
    if not trades_html:
        trades_html = '<tr><td colspan="6" class="muted">Aucun trade sur la periode.</td></tr>'

    r = detail.risk
    parts = []
    if r.get("stop_loss"):
        parts.append(f"stop −{r['stop_loss']*100:g}%")
    if r.get("trailing_stop"):
        parts.append(f"trailing {r['trailing_stop']*100:g}%")
    if r.get("take_profit"):
        parts.append(f"objectif +{r['take_profit']*100:g}%")
    if r.get("position_sizing") == "vol":
        parts.append(f"sizing vol {r['target_vol']*100:g}%")
    risk_badge = f'<span class="risk">{" · ".join(parts)}</span>' if parts else ""

    payload = json.dumps({"labels": labels, "equity": equity, "bh": bh,
                          "dd": dd, "comp": comp_chart})

    html = _TEMPLATE
    html = html.replace("%%TITLE%%", f"{context.get('symbol','ETH/USD')} · {detail.strategy_name}")
    html = html.replace("%%SUBTITLE%%",
                        f"{context.get('symbol','ETH/USD')} — {tf} — "
                        f"{df.index[0].strftime(fmt)} → {df.index[-1].strftime(fmt)}")
    html = html.replace("%%RISK%%", risk_badge)
    html = html.replace("%%CARDS%%", cards_html)
    html = html.replace("%%COMP_ROWS%%", comp_rows)
    html = html.replace("%%TRADES%%", trades_html)
    html = html.replace("/*PAYLOAD*/", payload)

    Path(path).write_text(html, encoding="utf-8")
    return path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#14110c; --panel:#1d1913; --panel2:#221d16;
  --line:rgba(214,170,90,.16); --gold:#d6aa5a; --gold-soft:rgba(214,170,90,.12);
  --up:#6fbf8a; --down:#df6a4f; --txt:#ece4d4; --muted:#928a78;
}
*{box-sizing:border-box}
body{
  margin:0; background:
    radial-gradient(1200px 600px at 80% -10%, rgba(214,170,90,.07), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(111,191,138,.05), transparent 60%),
    var(--bg);
  color:var(--txt); font-family:"IBM Plex Mono",monospace;
  -webkit-font-smoothing:antialiased; padding:38px 26px 60px; line-height:1.5;
}
.wrap{max-width:1180px; margin:0 auto}
header{border-bottom:1px solid var(--line); padding-bottom:22px; margin-bottom:30px}
.eyebrow{font-size:11px; letter-spacing:.32em; text-transform:uppercase; color:var(--gold); margin-bottom:10px}
h1{font-family:"Fraunces",serif; font-weight:900; font-size:clamp(30px,5vw,52px);
   margin:0; letter-spacing:-.01em; line-height:1.02}
.sub{color:var(--muted); font-size:13px; margin-top:12px; letter-spacing:.02em}
.risk{display:inline-block; margin-left:12px; padding:3px 10px; border:1px solid var(--line);
  border-radius:999px; color:var(--gold); font-size:11px; letter-spacing:.05em}
h2{font-family:"Fraunces",serif; font-weight:600; font-size:21px; letter-spacing:-.01em;
   margin:42px 0 16px; display:flex; align-items:baseline; gap:12px}
h2::after{content:""; flex:1; height:1px; background:var(--line)}
.grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel)); border:1px solid var(--line);
  border-radius:13px; padding:16px 17px}
.card-label{font-size:10.5px; letter-spacing:.13em; text-transform:uppercase; color:var(--muted)}
.card-value{font-family:"Fraunces",serif; font-weight:600; font-size:27px; margin-top:8px; letter-spacing:-.01em}
.up{color:var(--up)} .down{color:var(--down)} .neu{color:var(--txt)}
.panel{background:linear-gradient(180deg,var(--panel2),var(--panel)); border:1px solid var(--line);
  border-radius:15px; padding:20px 22px}
.chart-box{position:relative; height:360px}
.chart-box.sm{height:200px}
table{width:100%; border-collapse:collapse; font-size:12.5px}
th,td{text-align:right; padding:9px 10px; border-bottom:1px solid var(--line)}
th{color:var(--muted); font-weight:500; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase}
th:first-child,td:first-child,td.nm{text-align:left}
td.nm{color:var(--gold)}
tr:last-child td{border-bottom:none}
.badge{font-size:10px; padding:2px 8px; border-radius:999px; letter-spacing:.04em}
.b-stop{background:rgba(223,106,79,.15); color:var(--down)}
.b-tp{background:rgba(111,191,138,.15); color:var(--up)}
.b-sig{background:rgba(214,170,90,.13); color:var(--gold)}
.b-open{background:rgba(146,138,120,.15); color:var(--muted)}
.muted{color:var(--muted); text-align:center}
.cols{display:grid; grid-template-columns:1.1fr .9fr; gap:18px}
@media(max-width:840px){.cols{grid-template-columns:1fr}}
footer{margin-top:46px; padding-top:20px; border-top:1px solid var(--line);
  color:var(--muted); font-size:11.5px; line-height:1.7}
footer b{color:var(--gold); font-weight:500}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">Tableau de bord · backtest</div>
    <h1>%%TITLE%%</h1>
    <div class="sub">%%SUBTITLE%% %%RISK%%</div>
  </header>

  <div class="grid">%%CARDS%%</div>

  <h2>Courbe de capital</h2>
  <div class="panel"><div class="chart-box"><canvas id="equity"></canvas></div></div>

  <h2>Drawdown</h2>
  <div class="panel"><div class="chart-box sm"><canvas id="dd"></canvas></div></div>

  <div class="cols">
    <div>
      <h2>Comparaison des stratégies</h2>
      <div class="panel"><div class="chart-box sm"><canvas id="comp"></canvas></div></div>
    </div>
    <div>
      <h2>Détail</h2>
      <div class="panel" style="overflow-x:auto">
        <table>
          <thead><tr><th>Stratégie</th><th>Rdt</th><th>Sharpe</th><th>DD</th><th>PF</th><th>Win</th><th>Trades</th></tr></thead>
          <tbody>%%COMP_ROWS%%</tbody>
        </table>
      </div>
    </div>
  </div>

  <h2>Derniers trades</h2>
  <div class="panel" style="overflow-x:auto">
    <table>
      <thead><tr><th>Entrée</th><th>Sortie</th><th>Prix in</th><th>Prix out</th><th>P&amp;L</th><th>Raison</th></tr></thead>
      <tbody>%%TRADES%%</tbody>
    </table>
  </div>

  <footer>
    <b>Avertissement.</b> Backtest sur données historiques Kraken. Les performances passées ne préjugent
    en rien des résultats futurs. Ceci n'est pas un conseil en investissement. Le trading de crypto
    comporte un risque de perte pouvant aller jusqu'à la totalité du capital engagé.
  </footer>
</div>

<script>
const D = /*PAYLOAD*/;
const gold="#d6aa5a", muted="#928a78", up="#6fbf8a", down="#df6a4f";
const grid="rgba(214,170,90,.10)";
Chart.defaults.font.family="'IBM Plex Mono', monospace";
Chart.defaults.color=muted; Chart.defaults.font.size=11;

const thin=(n)=>({maxTicksLimit:n, autoSkip:true});

new Chart(document.getElementById('equity'),{
  type:'line',
  data:{labels:D.labels, datasets:[
    {label:'Stratégie', data:D.equity, borderColor:gold, borderWidth:1.8,
     pointRadius:0, tension:.12, fill:true,
     backgroundColor:(c)=>{const g=c.chart.ctx.createLinearGradient(0,0,0,360);
       g.addColorStop(0,'rgba(214,170,90,.22)'); g.addColorStop(1,'rgba(214,170,90,0)'); return g;}},
    {label:'Buy & Hold', data:D.bh, borderColor:muted, borderWidth:1.2,
     borderDash:[5,4], pointRadius:0, tension:.12, fill:false}
  ]},
  options:{responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
    plugins:{legend:{labels:{boxWidth:14, boxHeight:2, usePointStyle:false}},
      tooltip:{callbacks:{label:(c)=>c.dataset.label+': '+Number(c.parsed.y).toLocaleString('fr-FR')+' $'}}},
    scales:{x:{grid:{color:grid}, ticks:thin(8)}, y:{grid:{color:grid},
      ticks:{callback:(v)=>(v/1000).toFixed(0)+'k $'}}}}
});

new Chart(document.getElementById('dd'),{
  type:'line',
  data:{labels:D.labels, datasets:[{label:'Drawdown', data:D.dd, borderColor:down,
    borderWidth:1.2, pointRadius:0, tension:.1, fill:true,
    backgroundColor:'rgba(223,106,79,.18)'}]},
  options:{responsive:true, maintainAspectRatio:false,
    plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c)=>c.parsed.y.toFixed(1)+'%'}}},
    scales:{x:{grid:{color:grid}, ticks:thin(8)}, y:{grid:{color:grid},
      ticks:{callback:(v)=>v+'%'}}}}
});

new Chart(document.getElementById('comp'),{
  type:'bar',
  data:{labels:D.comp.map(o=>o.name), datasets:[{data:D.comp.map(o=>o.ret),
    backgroundColor:D.comp.map(o=>o.ret>=0?'rgba(111,191,138,.75)':'rgba(223,106,79,.75)'),
    borderColor:D.comp.map(o=>o.ret>=0?up:down), borderWidth:1, borderRadius:4}]},
  options:{responsive:true, maintainAspectRatio:false,
    plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c)=>c.parsed.y.toFixed(1)+'%'}}},
    scales:{x:{grid:{display:false}, ticks:{maxRotation:0, font:{size:9.5}}},
      y:{grid:{color:grid}, ticks:{callback:(v)=>v+'%'}}}}
});
</script>
</body>
</html>"""
