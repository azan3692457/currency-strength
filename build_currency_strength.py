"""Build the Currency Strength page: each of the 8 major currencies' gain or
loss against an equal-weighted basket of all 8, on 1-hour and 4-hour bars,
from OANDA mid prices for all 28 pairs. Needs OANDA_API_KEY in the
environment or in .env in the working directory.

long-comment-ok: the usage block and the exact-split note are the interface

  python3 currency-strength-site/build_currency_strength.py          # from ~/Desktop/testing
  python3 build_currency_strength.py --out public/index.html         # what GitHub Actions runs
  python3 build_currency_strength.py --live                          # use the live-trading host

A currency's basket value at each bar is the average of its log price against
all 8 currencies (itself counting as 0). Score over N bars is the change in
that value, in percent. Because the basket averages over 8, not 7, the first
currency's score minus the second's equals the pair's own log move, to
within about a pip of quote noise, so each pair's move splits into its two sides.
"""

import argparse
import datetime as dt
import json
import math
import os
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
LIVE_HOST = "https://api-fxtrade.oanda.com"


def load_api_key():
    """OANDA_API_KEY from the environment (GitHub Actions), else from .env in the working directory."""
    key = os.environ.get("OANDA_API_KEY")
    if key:
        return key.strip()
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("OANDA_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("OANDA_API_KEY not set (environment or .env)")


NY = ZoneInfo("America/New_York")
# Market-convention priority: pairing each currency with every later one
# yields the 28 real OANDA instrument names (EUR_USD, GBP_JPY, ... never USD_EUR).
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
PAIRS = [f"{a}_{b}" for i, a in enumerate(ORDER) for b in ORDER[i + 1:]]
DISPLAY = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]
# Same order and grouping as Market View's tables; EURGBP isn't there, so it goes last.
MAJORS = ["GBP_USD", "EUR_USD", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD"]
CROSSES = ["USD_JPY", "GBP_JPY", "EUR_JPY", "AUD_JPY", "EUR_GBP"]

# (granularity, lookback bars for the score, bars shown on the chart)
FRAMES = {"H1": (24, 72), "H4": (30, 120)}
# Bars in the "recent move" column: 4 hours on the 1h tab, 12 hours on the 4h tab.
RECENT = {"H1": 4, "H4": 3}
FETCH_COUNT = 400
PACE_SECONDS = 0.25


def fetch(host, key, pair, gran):
    url = (f"{host}/v3/instruments/{pair}/candles?granularity={gran}&price=M"
           f"&count={FETCH_COUNT}&alignmentTimezone=America%2FNew_York&dailyAlignment=17")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as resp:
                candles = json.load(resp)["candles"]
            return {c["time"][:19]: float(c["mid"]["c"]) for c in candles if c["complete"]}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("OANDA: 401 Unauthorized -- check OANDA_API_KEY in .env")
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def frame_payload(host, key, gran, lookback, shown):
    series = {}
    for p in PAIRS:
        series[p] = fetch(host, key, p, gran)
        time.sleep(PACE_SECONDS)
    # Keep only bar times every pair has, so each row is one consistent snapshot.
    times = sorted(set.intersection(*(set(s) for s in series.values())))
    basket = {c: [] for c in ORDER}
    for t in times:
        acc = {c: 0.0 for c in ORDER}
        for p in PAIRS:
            base, quote = p.split("_")
            lp = math.log(series[p][t])
            acc[base] += lp
            acc[quote] -= lp
        for c in ORDER:
            basket[c].append(acc[c] / 8)

    n = len(times)
    win = range(max(lookback, n - shown), n)
    start = win[0]
    stamps = [dt.datetime.fromisoformat(times[i]).replace(tzinfo=dt.timezone.utc)
              .astimezone(NY).strftime("%Y-%m-%d %H:%M") for i in win]
    # Chart: each bar's rolling score, the gain or loss over the `lookback` bars ending there,
    # so a drawn point never changes and the last point equals the ranking.
    lines = {c: [round((basket[c][i] - basket[c][i - lookback]) * 100, 3) for i in win] for c in ORDER}
    score = {c: round((basket[c][-1] - basket[c][-1 - lookback]) * 100, 3) for c in ORDER}
    last = {c: round((basket[c][-1] - basket[c][-2]) * 100, 3) for c in ORDER}
    recent = {c: round((basket[c][-1] - basket[c][-1 - RECENT[gran]]) * 100, 3) for c in ORDER}

    def pair_row(p):
        base, quote = p.split("_")
        move = (math.log(series[p][times[-1]]) - math.log(series[p][times[-1 - lookback]])) * 100
        return {"pair": p.replace("_", ""), "base": base, "quote": quote,
                "move": round(move, 3), "b": score[base], "q": score[quote]}

    return {"gran": gran, "lookback": lookback, "bars": len(times),
            "from": stamps[0], "to": stamps[-1],
            "lb_from": dt.datetime.fromisoformat(times[-1 - lookback]).replace(tzinfo=dt.timezone.utc)
                         .astimezone(NY).strftime("%Y-%m-%d %H:%M"),
            "t": stamps, "lines": lines, "score": score, "last": last, "recent": recent, "nrecent": RECENT[gran],
            "pairs": [pair_row(p) for p in MAJORS + CROSSES]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="currency_strength.html")
    ap.add_argument("--live", action="store_true", help="use the live-trading host instead of practice")
    a = ap.parse_args()
    host = LIVE_HOST if a.live else PRACTICE_HOST
    key = load_api_key()

    payload = {"display": DISPLAY,
               "frames": {g: frame_payload(host, key, g, lb, shown) for g, (lb, shown) in FRAMES.items()}}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"))))
    print(f"{a.out}  ({os.path.getsize(a.out) / 1024:.0f} KB)")
    for g, fr in payload["frames"].items():
        rank = sorted(fr["score"].items(), key=lambda kv: -kv[1])
        print(f"  {g} {fr['lookback']}-bar, to {fr['to']} NY: "
              + "  ".join(f"{c} {v:+.2f}" for c, v in rank))


HTML_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Currency Strength</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;450;500;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>
:root{
  --paper:#f4f6f8; --surface:#ffffff; --ink:#151922; --muted:#646d80;
  --rule:#dbdfe7; --rule-soft:#e9ecf1;
  --up:#2d7a70; --dn:#ab5540;
  --up-vivid:#16a34a; --dn-vivid:#dc2626;
  --shadow:0 1px 2px rgba(21,25,34,.05), 0 6px 18px rgba(21,25,34,.05);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --s5:#e87ba4; --s6:#008300; --s7:#4a3aa7; --s8:#e34948;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --paper:#11141b; --surface:#171b24; --ink:#e6e9ef; --muted:#8e97a9;
    --rule:#272d3a; --rule-soft:#1f242f;
    --up:#46a094; --dn:#c87a60;
    --up-vivid:#4ade80; --dn-vivid:#f87171;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.3);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
    --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --paper:#11141b; --surface:#171b24; --ink:#e6e9ef; --muted:#8e97a9;
  --rule:#272d3a; --rule-soft:#1f242f;
  --up:#46a094; --dn:#c87a60;
  --up-vivid:#4ade80; --dn-vivid:#f87171;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.3);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
}
*{box-sizing:border-box}
body{background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55; margin:0; -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px; margin:0 auto; padding-inline:20px; padding-block:56px 72px}
header{border-bottom:1px solid var(--rule); padding-bottom:26px; margin-bottom:34px}
h1{font-family:"IBM Plex Serif",Georgia,serif; font-weight:600;
  font-size:clamp(28px,4.4vw,40px); line-height:1.12; letter-spacing:-.015em; margin:0 0 12px}
.meta{display:flex; flex-wrap:wrap; gap:10px 28px; font-size:12.5px; margin:0}
.meta div{display:flex; flex-direction:column; gap:1px}
.meta dt{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); font-weight:600}
.meta dd{margin:0; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:13px; font-variant-numeric:tabular-nums}
h2{font-family:"IBM Plex Serif",Georgia,serif; font-weight:600; font-size:19px; letter-spacing:-.01em; margin:0 0 4px}
.lede{color:var(--muted); font-size:14px; margin:0 0 18px}
section{margin-bottom:48px}
.panel{background:var(--surface); border:1px solid var(--rule); border-radius:6px;
  box-shadow:var(--shadow); padding:16px 16px 12px; margin-bottom:16px; position:relative}
.ctitle{font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:600; margin:0 0 6px}
.cnote{text-transform:none; letter-spacing:0; font-weight:400}
svg{display:block; width:100%; height:auto; overflow:visible}
.grid{stroke:var(--rule-soft); stroke-width:1}
.zero{stroke:var(--muted); stroke-width:1; stroke-dasharray:3 3; opacity:.7}
.axlab{fill:var(--muted); font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:10px}
.dlab{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11px; font-weight:600; fill:var(--ink)}
.pl{paint-order:stroke; stroke:var(--surface); stroke-width:3px; stroke-linejoin:round}

.tabs{display:flex; gap:6px; margin:0 0 18px}
.tabs button{font:600 12.5px "IBM Plex Mono",ui-monospace,monospace; padding:6px 14px; border-radius:5px;
  border:1px solid var(--rule); background:var(--surface); color:var(--muted); cursor:pointer}
.tabs button[aria-pressed="true"]{color:var(--ink); border-color:var(--ink)}

.two{display:grid; grid-template-columns:1fr 1fr; gap:16px}
@media (max-width:860px){.two{grid-template-columns:1fr}}

.stable-wrap{overflow-x:auto}
.stable{border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums}
.stable th, .stable td{padding:6px 10px; text-align:right; white-space:nowrap; border-bottom:1px solid var(--rule-soft);
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.stable th{font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:600; border-bottom:1px solid var(--rule)}
.stable td:first-child, .stable th:first-child{text-align:left; font-weight:600}
.stable .neg{color:var(--dn-vivid)} .stable .pos{color:var(--up-vivid)} .stable .flat{color:var(--muted)}
.stable .grp{border-left:1px solid var(--rule-soft)}
.stable tbody tr:hover td{background:var(--rule-soft)}
.stable tr.div-top td{border-top:2px solid var(--rule)}
.stable tr.latest td{background:color-mix(in srgb, var(--s1) 12%, transparent); font-weight:600}
.stable tr.latest td:first-child{box-shadow:inset 3px 0 0 var(--s1)}
.sw{display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:7px; vertical-align:0}
.barcell{width:38%; min-width:140px}
.bar{position:relative; height:12px}
.bar .mid{position:absolute; left:50%; top:-3px; bottom:-3px; width:1px; background:var(--rule)}
.bar .fill{position:absolute; top:0; height:12px; border-radius:2px}
.pill{display:inline-block; padding:2px 9px; border-radius:20px; font-size:10.5px; font-weight:600; letter-spacing:.03em}
.pill-b{background:color-mix(in srgb, var(--s1) 16%, transparent); color:var(--ink)}
.pill-m{background:var(--rule-soft); color:var(--muted)}
.splitbar{display:flex; height:10px; border-radius:2px; overflow:hidden; min-width:120px; background:var(--rule-soft); gap:2px}

.legend{display:flex; flex-wrap:wrap; gap:6px 16px; font:500 12px "IBM Plex Mono",ui-monospace,monospace; margin:0 0 8px}
.legend button{all:unset; cursor:pointer; display:inline-flex; align-items:center}
.legend button[aria-pressed="false"]{opacity:.35}
.tip{position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--rule);
  box-shadow:var(--shadow); border-radius:5px; padding:7px 10px; font:12px "IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums; min-width:150px}
.tip .h{color:var(--muted); font-size:11px; margin-bottom:4px}
.tip div.r{display:flex; justify-content:space-between; gap:14px}

.method{border-top:1px solid var(--rule); padding-top:22px; font-size:13.5px; color:var(--muted)}
.method h2{color:var(--ink); font-size:16px; margin-bottom:10px}
.method p{margin:0 0 10px}
</style></head>
<body>
<div class="wrap">
<header>
  <h1>Currency Strength</h1>
  <dl class="meta">
    <div><dt>Last bar</dt><dd id="m-asof">—</dd></div>
    <div><dt>Score window</dt><dd id="m-win">—</dd></div>
    <div><dt>Pairs</dt><dd>28 · OANDA mid</dd></div>
    <div><dt>Times</dt><dd>America/New_York</dd></div>
  </dl>
</header>

<div class="tabs" id="tabs">
  <button data-g="H1" aria-pressed="true">1 hour</button>
  <button data-g="H4" aria-pressed="false">4 hour</button>
</div>

<section>
  <h2>Ranking</h2>
  <p class="lede" id="rank-lede"></p>
  <div class="panel"><div class="stable-wrap"><table class="stable" id="rank"></table></div></div>
</section>

<section>
  <h2>Strength Over Time</h2>
  <p class="lede" id="chart-lede"></p>
  <div class="panel" id="chart-panel">
    <div class="legend" id="legend"></div>
    <div id="chart"></div>
    <div class="tip" id="tip" hidden></div>
  </div>
</section>

<section>
  <h2>What Drove Each Pair</h2>
  <p class="lede" id="drv-lede"></p>
  <div class="panel"><div class="stable-wrap"><table class="stable" id="drivers"></table></div></div>
</section>

<section class="method">
  <h2>How it's calculated</h2>
  <p>Each currency's value is its average log price against all eight currencies, itself counting as zero, so it measures the currency against an equal-weighted basket. A score is the change in that value over the window, in percent.</p>
  <p>Last hour is each currency's move in the newest bar alone. Last 4 hours is its move over the newest four bars (on the 4h tab, the newest three bars, 12 hours). A move that rounds to 0.00% shows grey.</p>
  <p>Because the average is over eight, the first currency's score minus the second's equals the pair's own move, give or take about a pip of quoting noise between the 28 prices. The driver table uses that to split each pair's move into its two sides. The side with the larger share drove the move.</p>
  <h2 style="margin-top:22px">4-hour candle times</h2>
  <p>Six candles a day. Times on this page are New York and mark when a bar opens, so a 4h bar shown as 13:00 closes at 17:00 New York, 14:00 Pacific. The week's first candle opens Sunday 14:00 Pacific and the last closes Friday 14:00 Pacific.</p>
  <div class="stable-wrap" style="max-width:600px"><table class="stable" id="c4h">
    <thead><tr><th>#</th><th class="grp">Opens NY</th><th>Closes NY</th><th class="grp">Opens Pacific</th><th>Closes Pacific</th><th></th></tr></thead>
    <tbody>
      <tr><td>1</td><td class="grp">17:00</td><td>21:00</td><td class="grp">14:00</td><td>18:00</td><td></td></tr>
      <tr><td>2</td><td class="grp">21:00</td><td>01:00</td><td class="grp">18:00</td><td>22:00</td><td></td></tr>
      <tr><td>3</td><td class="grp">01:00</td><td>05:00</td><td class="grp">22:00</td><td>02:00</td><td></td></tr>
      <tr><td>4</td><td class="grp">05:00</td><td>09:00</td><td class="grp">02:00</td><td>06:00</td><td></td></tr>
      <tr><td>5</td><td class="grp">09:00</td><td>13:00</td><td class="grp">06:00</td><td>10:00</td><td></td></tr>
      <tr><td>6</td><td class="grp">13:00</td><td>17:00</td><td class="grp">10:00</td><td>14:00</td><td></td></tr>
    </tbody></table></div>
</section>
</div>

<script>
const P = __PAYLOAD__;
const DISPLAY = P.display;
const COLOR = {}; DISPLAY.forEach((c,i)=>COLOR[c]=`var(--s${i+1})`);
let G = "H1";
// Shown by default: USD, EUR, GBP, JPY; click a legend entry to show the rest.
const hidden = new Set(["CHF", "AUD", "NZD", "CAD"]);

const fmtPct = (v, d=2) => `${v>=0?"+":"−"}${Math.abs(v).toFixed(d)}%`;
const cls = v => v>0 ? "pos" : v<0 ? "neg" : "";
// Recent-move cells: anything that rounds to 0.00% shows grey as "0.00%".
const r2 = v => Math.round(v*100)/100;
const clsR = v => r2(v)===0 ? "flat" : cls(v);
const fmtR = v => r2(v)===0 ? "0.00%" : fmtPct(v);
function fmtT(s){ const [d,t] = s.split(" "); const dd = new Date(d+"T00:00:00Z");
  return `${dd.toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",timeZone:"UTC"})} ${t}`; }
function spanLabel(f){ const hrs = f.lookback*(f.gran==="H1"?1:4), days = hrs/24;
  if(days===1) return "24 hours, 1 trading day";
  if(days===5) return "5 trading days, 1 week";
  return Number.isInteger(days) ? `${days} trading days` : `${hrs} hours`; }
const winLabel = f => `${f.lookback} × ${f.gran==="H1"?"1h":"4h"} bars (${spanLabel(f)})`;

function renderRank(f){
  const rows = DISPLAY.map(c=>({c, v:f.score[c], l:f.last[c], r:f.recent[c]})).sort((a,b)=>b.v-a.v);
  const unit = f.gran==="H1" ? 1 : 4, recentLbl = `Last ${f.nrecent*unit} hours`, lastLbl = unit===1 ? "Last hour" : "Last bar (4h)";
  const max = Math.max(...rows.map(r=>Math.abs(r.v)), 0.01);
  document.getElementById("rank").innerHTML = `<thead><tr><th>#</th><th style="text-align:left">Currency</th>
    <th>Gain / loss</th><th class="barcell"></th><th class="grp">${lastLbl}</th><th>${recentLbl}</th></tr></thead><tbody>${
    rows.map((r,i)=>{
      const w = Math.abs(r.v)/max*50;
      const fill = r.v>=0 ? `left:50%;width:${w}%` : `left:${50-w}%;width:${w}%`;
      return `<tr><td>${i+1}</td><td style="text-align:left"><span class="sw" style="background:${COLOR[r.c]}"></span>${r.c}</td>
        <td class="${cls(r.v)}">${fmtPct(r.v)}</td>
        <td class="barcell"><div class="bar"><div class="mid"></div><div class="fill" style="${fill};background:${COLOR[r.c]}"></div></div></td>
        <td class="grp ${clsR(r.l)}">${fmtR(r.l)}</td>
        <td class="${clsR(r.r)}">${fmtR(r.r)}</td></tr>`;}).join("")}</tbody>`;
  document.getElementById("rank-lede").textContent =
    `Each currency's gain or loss against an equal-weighted basket of all eight, over the last ${winLabel(f)}, from ${fmtT(f.lb_from)} to ${fmtT(f.to)}.`;
}

function renderDrivers(f){
  const rows = f.pairs.map((p,i)=>{
    const b = p.b, q = -p.q;   // q: the second currency's contribution to the pair's move
    const tot = Math.abs(b)+Math.abs(q) || 1;
    const bShare = Math.abs(b)/tot;
    const lead = bShare>=0.5 ? p.base : p.quote;
    const leadV = bShare>=0.5 ? p.b : p.q;
    const share = Math.round(Math.max(bShare,1-bShare)*100);
    const verdict = share < 60 ? `<span class="pill pill-m">Both</span>`
      : `<span class="pill pill-b">${lead} ${leadV>=0?"strength":"weakness"}</span>`;
    return `<tr class="${i===6?"div-top":""}"><td>${p.pair}</td><td class="${cls(p.move)}">${fmtPct(p.move)}</td>
      <td class="grp ${cls(p.b)}">${fmtPct(p.b)}</td><td class="${cls(p.q)}">${fmtPct(p.q)}</td>
      <td class="grp"><div class="splitbar"><div style="flex:${bShare*100};background:${COLOR[p.base]}"></div><div style="flex:${(1-bShare)*100};background:${COLOR[p.quote]}"></div></div></td>
      <td>${share}% ${bShare>=0.5?p.base:p.quote}</td><td style="text-align:left">${verdict}</td></tr>`;
  }).join("");
  document.getElementById("drivers").innerHTML = `<thead><tr><th>Pair</th><th>Pair move</th>
    <th class="grp">1st ccy</th><th>2nd ccy</th><th class="grp">Split</th><th>Larger side</th><th style="text-align:left">Driver</th></tr></thead><tbody>${rows}</tbody>`;
  document.getElementById("drv-lede").textContent =
    `Pair move = first currency's gain/loss − second currency's gain/loss, over the same ${winLabel(f)}. "Both" means neither side contributed 60% or more.`;
}

function renderLegend(){
  document.getElementById("legend").innerHTML = DISPLAY.map(c=>
    `<button data-c="${c}" aria-pressed="${!hidden.has(c)}"><span class="sw" style="background:${COLOR[c]}"></span>${c}</button>`).join("");
  document.querySelectorAll("#legend button").forEach(b=>b.onclick=()=>{
    const c=b.dataset.c; hidden.has(c)?hidden.delete(c):hidden.add(c); renderLegend(); renderChart(P.frames[G]); });
}

function niceStep(span){ const raw=span/6, m=Math.pow(10,Math.floor(Math.log10(raw)));
  return [1,2,2.5,5,10].map(k=>k*m).find(s=>s>=raw); }

function renderChart(f){
  const W=1100, H=420, L=48, R=56, T=10, B=28, PW=W-L-R, PH=H-T-B;
  const vis = DISPLAY.filter(c=>!hidden.has(c));
  const vals = vis.flatMap(c=>f.lines[c]).concat([0]);
  let lo=Math.min(...vals), hi=Math.max(...vals);
  const step=niceStep(hi-lo||0.1); lo=Math.floor(lo/step)*step; hi=Math.ceil(hi/step)*step;
  const n=f.t.length, x=i=>L+i/(n-1)*PW, y=v=>T+(hi-v)/(hi-lo)*PH;
  let s=`<svg viewBox="0 0 ${W} ${H}" id="csvg">`;
  for(let v=lo; v<=hi+1e-9; v+=step){
    s+=`<line class="grid" x1="${L}" x2="${L+PW}" y1="${y(v)}" y2="${y(v)}"/><text class="axlab" x="${L-6}" y="${y(v)+3}" text-anchor="end">${v.toFixed(step<0.1?2:1)}%</text>`;
  }
  s+=`<line class="zero" x1="${L}" x2="${L+PW}" y1="${y(0)}" y2="${y(0)}"/>`;
  // Day labels at the first bar of each New York date.
  let lastD=null, lastX=-1e9;
  f.t.forEach((t,i)=>{ const d=t.slice(0,10); if(d!==lastD){ lastD=d;
    if(x(i)-lastX>60){ lastX=x(i); const dd=new Date(d+"T00:00:00Z");
      s+=`<line class="grid" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${T+PH}"/><text class="axlab" x="${x(i)}" y="${H-8}" text-anchor="middle">${dd.toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"})}</text>`; } } });
  vis.forEach(c=>{
    const d=f.lines[c].map((v,i)=>`${i?"L":"M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    s+=`<path d="${d}" fill="none" stroke="${COLOR[c]}" stroke-width="2" stroke-linejoin="round"/>`;
  });
  // Direct labels at the right edge, nudged apart so they don't overlap.
  const ends = vis.map(c=>({c, y:y(f.lines[c][n-1])})).sort((a,b)=>a.y-b.y);
  for(let i=1;i<ends.length;i++) if(ends[i].y-ends[i-1].y<13) ends[i].y=ends[i-1].y+13;
  ends.forEach(e=>{ s+=`<text class="dlab pl" x="${L+PW+6}" y="${e.y+4}">${e.c}</text>`; });
  s+=`<line id="xh" x1="0" x2="0" y1="${T}" y2="${T+PH}" stroke="var(--muted)" stroke-width="1" visibility="hidden"/>`;
  s+=`<rect x="${L}" y="${T}" width="${PW}" height="${PH}" fill="transparent" id="hit"/></svg>`;
  document.getElementById("chart").innerHTML=s;

  const svg=document.getElementById("csvg"), tip=document.getElementById("tip"), xh=document.getElementById("xh");
  const panel=document.getElementById("chart-panel");
  document.getElementById("hit").onmousemove=ev=>{
    const pt=svg.createSVGPoint(); pt.x=ev.clientX; pt.y=ev.clientY;
    const sp=pt.matrixTransform(svg.getScreenCTM().inverse());
    const i=Math.max(0,Math.min(n-1,Math.round((sp.x-L)/PW*(n-1))));
    xh.setAttribute("x1",x(i)); xh.setAttribute("x2",x(i)); xh.setAttribute("visibility","visible");
    const rows=vis.map(c=>({c,v:f.lines[c][i]})).sort((a,b)=>b.v-a.v);
    tip.innerHTML=`<div class="h">${fmtT(f.t[i])}</div>`+rows.map(r=>
      `<div class="r"><span><span class="sw" style="background:${COLOR[r.c]}"></span>${r.c}</span><span>${fmtPct(r.v)}</span></div>`).join("");
    tip.hidden=false;
    const pr=panel.getBoundingClientRect();
    let left=ev.clientX-pr.left+14; if(left+170>pr.width) left=ev.clientX-pr.left-184;
    tip.style.left=left+"px"; tip.style.top=(ev.clientY-pr.top-20)+"px";
  };
  document.getElementById("hit").onmouseleave=()=>{ tip.hidden=true; xh.setAttribute("visibility","hidden"); };
  document.getElementById("chart-lede").textContent =
    `Each point is that bar's gain or loss over the previous ${winLabel(f)}, the same measure as the Ranking, for the last ${f.t.length} bars since ${fmtT(f.from)}. The last point of each line is its Ranking score. Above zero, the currency is up over that window; a rising line means its score is improving.`;
}

function render(){
  const f=P.frames[G];
  document.getElementById("m-asof").textContent=fmtT(f.to);
  document.getElementById("m-win").textContent=winLabel(f);
  renderRank(f); renderChart(f); renderDrivers(f);
}
document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{
  G=b.dataset.g; document.querySelectorAll("#tabs button").forEach(x=>x.setAttribute("aria-pressed",x===b)); render(); });
renderLegend(); render();
// Mark the 4h candle the latest pull ended on (bar open time, New York).
(function(){
  const last = P.frames.H4.to, open = last.slice(11);
  document.querySelectorAll("#c4h tbody tr").forEach(tr=>{
    const hit = tr.children[1].textContent === open;
    tr.classList.toggle("latest", hit);
    tr.lastElementChild.innerHTML = hit ? `<span class="pill pill-b">Latest · ${fmtT(last).split(" ").slice(0,3).join(" ")}</span>` : "";
  });
})();
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
