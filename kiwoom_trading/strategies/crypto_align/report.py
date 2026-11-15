"""🪜 이평선 재정배열 코인 선물 — 매매 타점 HTML 리포트.

    python -m kiwoom_trading.strategies.crypto_align.report [--symbol SOXLUSDT] [--fragment out.html]

- 모의 매매(state·trades.csv, 실제로 판정한 것)와 '지난 차트 타점'(같은 규칙을 상장일부터 다시 계산)을 함께 그림.
- 결과: data/reports/crypto_align_<심볼>.html (텔레그램 파일 전송용 전체 문서).
  --fragment 는 Artifact 게시용(doctype·html·body 없이)으로 따로 씀.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.strategies.crypto_align import core

KST = timezone(timedelta(hours=9))
SHIFT = 9 * 3600   # 차트 시간축을 한국 시각으로


def _kst(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d %H:%M")


def _stats(trades: list[dict], key: str = "net") -> dict:
    if not trades:
        return {"n": 0}
    r = [t[key] for t in trades]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    win = [x for x in r if x > 0]
    loss = [-x for x in r if x < 0]
    return {"n": len(r), "sum": sum(r) * 100, "avg": sum(r) / len(r) * 100, "win": len(win) / len(r) * 100,
            "pf": (sum(win) / sum(loss)) if loss else None, "comp": (eq - 1) * 100, "mdd": mdd * 100,
            "stops": sum(1 for t in trades if t["reason"].startswith("손절"))}


def _paper(symbol: str) -> tuple[list[dict], dict | None, dict | None]:
    from kiwoom_trading.strategies.crypto_align.live import load_trades
    d = core.data_dir(symbol)
    trades = load_trades(symbol)
    st = None
    sp = os.path.join(d, "state.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
    return trades, (st or {}).get("pos"), st


def build(symbol: str, bars: list[core.Bar] | None = None, fragment_path: str | None = None) -> str:
    if bars is None:
        bars, _ = core.load_bars(symbol)
    rates = core.load_funding(symbol)
    hist_state = core.State(last_t=0, cash=1000.0, cash2=1000.0)
    hist = core.replay(bars, hist_state, rates=rates)
    paper_rows, paper_pos, paper_state = _paper(symbol)

    candles = [[b.t // 1000 + SHIFT, round(b.o, 3), round(b.h, 3), round(b.l, 3), round(b.c, 3)] for b in bars]
    hist_js = [{"s": t["signal_t"] // 1000 + SHIFT, "e": t["entry_t"] // 1000 + SHIFT, "x": t["exit_t"] // 1000 + SHIFT,
                "ep": round(t["entry"], 3), "xp": round(t["exit"], 3), "r": round(t["net"] * 100, 2),
                "r2": round(t["net2"] * 100, 2),
                "why": t["reason"], "ek": _kst(t["entry_t"]), "xk": _kst(t["exit_t"])} for t in hist]
    paper_js = []
    for r in paper_rows:
        paper_js.append({"ek": _kst(r["entry_t"]), "xk": _kst(r["exit_t"]), "ep": r["entry"], "xp": r["exit"],
                         "r": round(r["net"] * 100, 2), "r2": round(r["net2"] * 100, 2), "why": r["reason"],
                         "cash": r["cash"], "cash2": r["cash2"]})
    hs = _stats(hist)
    hs2 = _stats(hist, "net2")
    start_kst = _kst(paper_state["last_t"]) if paper_state else None
    payload = {
        "symbol": symbol, "kind": core.KIND, "candles": candles, "hist": hist_js, "paper": paper_js,
        "paperPos": ({"ek": _kst(paper_pos["entry_t"]), "ep": paper_pos["entry"], "stop": paper_pos["stop"],
                      "e": paper_pos["entry_t"] // 1000 + SHIFT} if paper_pos else None),
        "paperCash": paper_state["cash"] if paper_state else None,
        "paperCash2": paper_state.get("cash2", paper_state["cash"]) if paper_state else None, "paperStart": start_kst,
        "stats": hs, "stats2": hs2, "first": _kst(bars[0].t), "last": _kst(bars[-1].t + core.BAR_MS),
        "lastPrice": bars[-1].c, "firstPrice": bars[0].o,
        "built": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    }
    body = (TEMPLATE.replace("__SYMBOL__", symbol).replace("__ABBR__", core.abbr_footer(symbol).replace("약어 풀이 — ", ""))
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
    out_dir = os.path.join(PROJECT_ROOT, "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"crypto_align_{symbol}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
                "</head><body>" + body + "</body></html>")
    if fragment_path:
        with open(fragment_path, "w", encoding="utf-8") as f:
            f.write(body)
    return path


TEMPLATE = r"""<title>__SYMBOL__ 재정배열 타점</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* 레이아웃: 위에 규칙 한 줄 + 숫자 띠, 가운데 큰 15분봉 차트(타점 표시), 아래 잔고 곡선과 매매 표 */
:root{
  --bg:#f3f5f7; --panel:#ffffff; --fg:#17202a; --muted:#5d6b7a; --line:#d9dfe6;
  --accent:#0f7c8c; --up:#14935f; --down:#d0443a; --pending:#b7791f; --grid:#e8ecf0;
  --f-body:"IBM Plex Sans KR",system-ui,-apple-system,"Malgun Gothic",sans-serif;
  --f-num:"JetBrains Mono",ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f1419; --panel:#161d24; --fg:#e4e9ee; --muted:#8b98a6; --line:#26313b;
  --accent:#3fb6c6; --up:#3cc48a; --down:#f06a5f; --pending:#e0a84a; --grid:#1d262f; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f1419; --panel:#161d24; --fg:#e4e9ee; --muted:#8b98a6; --line:#26313b;
  --accent:#3fb6c6; --up:#3cc48a; --down:#f06a5f; --pending:#e0a84a; --grid:#1d262f; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--f-body);font-size:14px;line-height:1.55;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding-block:20px 40px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  display:flex;flex-direction:column;gap:18px}
header h1{font-size:22px;margin:0;text-wrap:balance;font-weight:700}
header h1 .sym{font-family:var(--f-num);font-weight:600;color:var(--accent)}
.rule{color:var(--muted);margin:6px 0 0;max-width:80ch}
.band{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:6px;overflow:hidden}
.band>div{background:var(--panel);padding:10px 14px;min-width:0}
.band .k{font-size:11.5px;color:var(--muted);letter-spacing:.02em}
.band .v{font-family:var(--f-num);font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.pos{color:var(--up)} .neg{color:var(--down)}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;min-width:0}
.sec h2{font-size:15px;margin:0 0 4px;font-weight:700}
.sec .sub{color:var(--muted);font-size:12.5px;margin:0 0 10px}
#chart{height:520px;width:100%}
#eq{height:200px;width:100%}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin-top:8px}
.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px;border-radius:2px}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:3px 10px;border-radius:999px;
  border:1px solid var(--line);color:var(--muted)}
.status b{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.status.hold b{background:var(--pending)} .status.flat b{background:var(--accent)}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--muted);font-weight:500;position:sticky;top:0;background:var(--panel)}
td:first-child,th:first-child,td.l,th.l{text-align:left}
td.num{font-family:var(--f-num)}
tbody tr{cursor:pointer} tbody tr:hover{background:var(--grid)}
tbody tr:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.tabs{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.tabs button{font:inherit;font-size:12.5px;padding:4px 12px;border-radius:4px;border:1px solid var(--line);
  background:transparent;color:var(--fg);cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--accent);border-color:var(--accent);color:var(--panel)}
.tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.empty{color:var(--muted);padding:14px 4px}
footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px}
footer p{margin:2px 0}
@media (max-width:520px){#chart{height:400px} header h1{font-size:19px}}
</style>
<div class="wrap">
<header>
  <h1>🪜 이평선 재정배열 · <span class="sym" id="sym"></span> 매매 타점</h1>
  <p class="rule">15분봉 60선이 120선을 아래에서 위로 넘고 종가가 60선 위면 다음 봉 시가에 롱 매수함. 매수가 −3% 손절, 익절 없음, 손절이 안 걸리면 다음 날 09:00(한국 시각) 첫 봉 시가에 매도함. 같은 매매를 1배·2배 두 가상 잔고로 적음. 수수료 0.05%×2와 펀딩비(8시간마다) 포함. 실제 주문은 내지 않음.</p>
</header>

<div class="band" id="band"></div>

<section class="sec">
  <h2>15분봉 차트와 타점</h2>
  <p class="sub" id="chartSub"></p>
  <div id="chart" role="img" aria-label="15분봉 캔들 차트와 매수·매도 표시"></div>
  <div class="legend">
    <span><i style="background:var(--accent)"></i>60선</span>
    <span><i style="background:var(--pending)"></i>120선</span>
    <span>▲ 매수 · ▼ 매도 (초록 = 이익, 빨강 = 손실)</span>
    <span>표의 줄을 누르면 그 매매로 이동함</span>
  </div>
</section>

<section class="sec">
  <h2>가상 잔고 곡선</h2>
  <p class="sub">1,000 USDT 로 시작해 매매마다 전부 굴렸을 때의 잔고임 (복리). 진한 선 = 1배, 연한 선 = 2배.</p>
  <div id="eq"></div>
</section>

<section class="sec">
  <h2>매매 목록</h2>
  <div class="tabs" role="tablist">
    <button role="tab" id="tabPaper" aria-selected="true">모의 매매</button>
    <button role="tab" id="tabHist" aria-selected="false">지난 차트 타점</button>
  </div>
  <div class="tbl"><table><thead><tr>
    <th class="l">#</th><th class="l">매수 (한국 시각)</th><th>매수가</th><th class="l">매도</th><th>매도가</th>
    <th class="l">매도 이유</th><th>1배</th><th>2배</th></tr></thead><tbody id="rows"></tbody></table></div>
</section>

<footer>
  <p id="built"></p>
  <p>__ABBR__</p>
</footer>
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (x, d=2) => Number(x).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const pct = x => (x>0?'+':'') + fmt(x,2) + '%';
const cls = x => x>0 ? 'pos' : (x<0 ? 'neg' : '');

$('sym').textContent = D.symbol;
$('chartSub').textContent = `${D.first} ~ ${D.last} (한국 시각), 15분봉 ${D.candles.length.toLocaleString()}개. 모의 매매도 같은 규칙이라 시작 뒤 타점은 같은 자리에 찍힘.`;
$('built').textContent = `리포트 만든 때 ${D.built} · 시세: 바이낸스 USDT 무기한 선물 공개 시세`;

// 숫자 띠
const S = D.stats, hold = D.lastPrice / D.firstPrice * 100 - 100;
const paperN = D.paper.length, paperCash = D.paperCash, paperCash2 = D.paperCash2, S2 = D.stats2;
const items = [
  ['모의 매매 상태', D.paperPos ? `보유 중` : (D.paperStart ? '기다리는 중' : '시작 전'), ''],
  ['모의 잔고 1배 (USDT)', paperCash!=null ? fmt(paperCash,1) : '—', paperCash!=null ? cls(paperCash-1000) : ''],
  ['모의 잔고 2배 (USDT)', paperCash2!=null ? fmt(paperCash2,1) : '—', paperCash2!=null ? cls(paperCash2-1000) : ''],
  ['모의 매매 건수', String(paperN), ''],
  ['지난 차트 타점', `${S.n}건`, ''],
  ['지난 타점 복리 1배', pct(S.comp), cls(S.comp)],
  ['지난 타점 복리 2배', pct(S2.comp), cls(S2.comp)],
  ['최대 낙폭 1배 · 2배', `${pct(S.mdd)} · ${pct(S2.mdd)}`, 'neg'],
  ['그냥 들고 있었다면', pct(hold), cls(hold)],
];
$('band').innerHTML = items.map(([k,v,c]) => `<div><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');
if (D.paperPos) {
  $('band').firstElementChild.querySelector('.v').innerHTML =
    `<span class="status hold"><b></b>보유 ${fmt(D.paperPos.ep)}</span>`;
}

// 차트
let chart, candle, ma60, ma120, eqChart, eqLine, eqLine2;
function sma(n){ const out=[]; let s=0; D.candles.forEach((c,i)=>{ s+=c[4]; if(i>=n) s-=D.candles[i-n][4];
  if(i>=n-1) out.push({time:c[0], value:+(s/n).toFixed(3)}); }); return out; }
function markers(){
  const up=css('--up'), down=css('--down'), m=[];
  const fade = c => c + '88';
  D.hist.forEach((t,i)=>{
    const c = t.r>0 ? up : down;
    m.push({time:t.e, position:'belowBar', color:fade(c), shape:'arrowUp', text:''});
    m.push({time:t.x, position:'aboveBar', color:fade(c), shape:'arrowDown', text:pct(t.r)});
  });
  if (D.paperPos) m.push({time:D.paperPos.e, position:'belowBar', color:css('--pending'), shape:'arrowUp', text:'모의 보유'});
  return m.sort((a,b)=>a.time-b.time);
}
function themeOpts(){ return {
  layout:{background:{type:'solid', color:css('--panel')}, textColor:css('--muted'), fontFamily:css('--f-body')},
  grid:{vertLines:{color:css('--grid')}, horzLines:{color:css('--grid')}},
  rightPriceScale:{borderColor:css('--line')}, timeScale:{borderColor:css('--line'), timeVisible:true, secondsVisible:false},
}; }
function build(){
  if (!window.LightweightCharts){ $('chart').innerHTML='<p class="empty">차트 라이브러리를 불러오지 못함 (인터넷 연결 필요).</p>'; return; }
  chart = LightweightCharts.createChart($('chart'), {...themeOpts(), autoSize:true, crosshair:{mode:0}});
  candle = chart.addCandlestickSeries({upColor:css('--up'), downColor:css('--down'), borderVisible:false,
    wickUpColor:css('--up'), wickDownColor:css('--down')});
  candle.setData(D.candles.map(c=>({time:c[0], open:c[1], high:c[2], low:c[3], close:c[4]})));
  ma60 = chart.addLineSeries({color:css('--accent'), lineWidth:1.5, priceLineVisible:false, lastValueVisible:false});
  ma120 = chart.addLineSeries({color:css('--pending'), lineWidth:1.5, priceLineVisible:false, lastValueVisible:false});
  ma60.setData(sma(60)); ma120.setData(sma(120));
  candle.setMarkers(markers());
  if (D.paperPos) candle.createPriceLine({price:D.paperPos.stop, color:css('--down'), lineStyle:2, title:'손절'});
  const n = D.candles.length; chart.timeScale().setVisibleLogicalRange({from:n-96*5, to:n+4});

  eqChart = LightweightCharts.createChart($('eq'), {...themeOpts(), autoSize:true, handleScroll:false, handleScale:false});
  eqLine = eqChart.addAreaSeries({lineColor:css('--accent'), topColor:css('--accent')+'44', bottomColor:css('--accent')+'05', lineWidth:2});
  eqLine2 = eqChart.addLineSeries({color:css('--accent')+'77', lineWidth:1.5, priceLineVisible:false, lastValueVisible:true});
  let eq=1000, eq2=1000; const pts=[{time:D.candles[0][0], value:1000}], pts2=[{time:D.candles[0][0], value:1000}];
  D.hist.forEach(t=>{ eq*=1+t.r/100; eq2*=1+t.r2/100; pts.push({time:t.x, value:+eq.toFixed(2)}); pts2.push({time:t.x, value:+eq2.toFixed(2)}); });
  eqLine.setData(dedupe(pts)); eqLine2.setData(dedupe(pts2)); eqChart.timeScale().fitContent();
}
function dedupe(p){ const o=[]; p.forEach(x=>{ if(o.length && o[o.length-1].time>=x.time) o[o.length-1]=x; else o.push(x); }); return o; }
function retheme(){ if(!chart) return; chart.applyOptions(themeOpts()); eqChart.applyOptions(themeOpts());
  candle.applyOptions({upColor:css('--up'), downColor:css('--down'), wickUpColor:css('--up'), wickDownColor:css('--down')});
  ma60.applyOptions({color:css('--accent')}); ma120.applyOptions({color:css('--pending')});
  eqLine.applyOptions({lineColor:css('--accent'), topColor:css('--accent')+'44', bottomColor:css('--accent')+'05'});
  eqLine2.applyOptions({color:css('--accent')+'77'});
  candle.setMarkers(markers()); }
function focusTrade(t){ if(!chart) return; const span=(t.x-t.e); chart.timeScale().setVisibleRange({from:t.e-Math.max(span,6*3600)*1.2-8*3600, to:t.x+Math.max(span,6*3600)*0.6});
  $('chart').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth', block:'center'}); }

// 표
let tab = 'paper';
function rows(){
  const tb = $('rows');
  if (tab==='paper'){
    if (!D.paper.length){
      const msg = D.paperPos ? `지금 보유 중: ${D.paperPos.ek} 매수 ${fmt(D.paperPos.ep)}, 손절 ${fmt(D.paperPos.stop)}.`
        : `아직 끝난 모의 매매가 없음. ${D.paperStart ? D.paperStart + ' 봉 다음부터 15분마다 판정 중.' : ''}`;
      tb.innerHTML = `<tr><td colspan="8" class="empty l">${msg}</td></tr>`; return; }
    tb.innerHTML = D.paper.map((t,i)=>`<tr tabindex="0"><td class="l">${i+1}</td><td class="l">${t.ek}</td><td class="num">${fmt(t.ep)}</td><td class="l">${t.xk}</td><td class="num">${fmt(t.xp)}</td><td class="l">${t.why}</td><td class="num ${cls(t.r)}">${pct(t.r)}</td><td class="num ${cls(t.r2)}">${pct(t.r2)}</td></tr>`).join('');
    return;
  }
  tb.innerHTML = D.hist.map((t,i)=>`<tr tabindex="0" data-i="${i}"><td class="l">${i+1}</td><td class="l">${t.ek}</td><td class="num">${fmt(t.ep)}</td><td class="l">${t.xk}</td><td class="num">${fmt(t.xp)}</td><td class="l">${t.why}</td><td class="num ${cls(t.r)}">${pct(t.r)}</td><td class="num ${cls(t.r2)}">${pct(t.r2)}</td></tr>`).reverse().join('');
}
$('rows').addEventListener('click', e=>{ const tr=e.target.closest('tr[data-i]'); if(tr) focusTrade(D.hist[+tr.dataset.i]); });
$('rows').addEventListener('keydown', e=>{ if(e.key==='Enter'){ const tr=e.target.closest('tr[data-i]'); if(tr) focusTrade(D.hist[+tr.dataset.i]); }});
function setTab(t){ tab=t; $('tabPaper').setAttribute('aria-selected', t==='paper'); $('tabHist').setAttribute('aria-selected', t==='hist'); rows(); }
$('tabPaper').onclick=()=>setTab('paper'); $('tabHist').onclick=()=>setTab('hist');
if (!D.paper.length && !D.paperPos) setTab('hist'); else rows();

build();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', retheme);
new MutationObserver(retheme).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SOXLUSDT")
    ap.add_argument("--fragment")
    a = ap.parse_args()
    print(build(a.symbol, fragment_path=a.fragment))


if __name__ == "__main__":
    main()
