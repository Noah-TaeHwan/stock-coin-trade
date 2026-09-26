/* 코인 차익·김프 화면. 서버 /api/arb/*가 계산한 공개 시세 결과를 그린다.
   주문·출금 기능은 없고, 시뮬레이터는 서버의 호가 기반 모의 계산을 보여 준다. */

const ARB_FAST_MS = 10_000;
const ARB_SLOW_MS = 60_000;
const ARB_SOURCES = ['UPBIT', 'BITHUMB', 'COINONE', 'KORBIT', 'OKX', 'BINANCE', 'FX'];
const ARB_SOURCE_NAMES = { UPBIT: '업비트', BITHUMB: '빗썸', COINONE: '코인원', KORBIT: '코빗', OKX: 'OKX', BINANCE: 'Binance', FX: '환율', MEMPOOL: 'mempool' };
const ARB_STATUS_TEXT = { ok: '정상', error: '실패', blocked: '지역 제한' };

const arb = {
  symbol: 'BTC',
  interval: '1H',
  sort: { key: 'kimpUsdtPct', dir: -1 },
  sizeKrw: 1_000_000,
  feeOverrides: {},
  withdrawOverride: null,
  pick: null,            // 사용자가 고른 {buy, sell}. 없으면 최적 쌍을 쓴다.
  snapshot: null,
  matrix: null,
  network: null,
  history: null,
};

let arbChart = null;
let arbSeries = null;
let arbPointsByTime = new Map();
let arbMatrixSeq = 0;
let arbMatrixTimer = null;

/* ── 서식 ───────────────────────────────────────────────────────────────── */
const esc = escapeHtml;
const isNum = v => typeof v === 'number' && Number.isFinite(v);
const fmtKrw = v => isNum(v) ? v.toLocaleString('ko-KR', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 4 }) : '-';
const fmtPct = (v, d = 2) => isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}%` : '-';
const fmtSignedKrw = v => isNum(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v)).toLocaleString('ko-KR')}원` : '-';
const fmtCoin = v => isNum(v) ? v.toLocaleString('ko-KR', { maximumFractionDigits: 8 }) : '-';
const exName = code => arb.snapshot?.exchanges?.[code]?.name || ARB_SOURCE_NAMES[code] || code;
const isGlobal = code => arb.snapshot?.exchanges?.[code]?.quote === 'USDT';
const kstFmt = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

function parseNum(text) {
  const n = Number(String(text).replaceAll(',', '').trim());
  return Number.isFinite(n) ? n : null;
}

// 순손익 %를 배경 농도로 바꾼다. 부호는 숫자에도 붙이므로 색만으로 구분하지 않는다.
function heatStyle(pct) {
  if (!isNum(pct) || Math.abs(pct) < 0.05) return 'background:var(--surface-2);';
  const c = termColors();
  const alpha = Math.min(0.1 + Math.abs(pct) / 2 * 0.35, 0.45);
  return `background:${termAlpha(pct > 0 ? c.up : c.down, alpha.toFixed(2))};`;
}

async function arbGet(path) {
  const res = await apiFetch(path);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
  return body;
}

/* ── 스냅샷: 코인 목록·지표·소스 상태 ────────────────────────────────────── */
async function loadSnapshot() {
  try {
    arb.snapshot = await arbGet('/api/arb/snapshot');
    renderCoinList();
    renderKpis();
    renderSources();
    renderExchangePremiums();
    renderNetwork();
  } catch (err) {
    const body = document.getElementById('coinListBody');
    if (body && !arb.snapshot) body.innerHTML = `<tr><td class="empty" colspan="4">시세를 불러오지 못했습니다: ${esc(err.message)}</td></tr>`;
  }
}

function coinRows() {
  const rows = (arb.snapshot?.coins || []).map(c => ({ ...c, domesticPct: c.domesticSpread?.pct }));
  const { key, dir } = arb.sort;
  return rows.sort((a, b) => {
    if (key === 'symbol') return a.symbol.localeCompare(b.symbol) * dir;
    const av = isNum(a[key]) ? a[key] : -Infinity;
    const bv = isNum(b[key]) ? b[key] : -Infinity;
    return (av - bv) * dir;
  });
}

function renderCoinList() {
  const body = document.getElementById('coinListBody');
  if (!body) return;
  body.innerHTML = coinRows().map(c => {
    const ref = c.domesticRef ? c.prices[c.domesticRef].krw : null;
    const spread = c.domesticSpread?.pct;
    const spreadTitle = spread != null ? `${exName(c.domesticSpread.low)} 최저 → ${exName(c.domesticSpread.high)} 최고` : '';
    return `<tr data-symbol="${c.symbol}" class="${c.symbol === arb.symbol ? 'is-selected' : ''}">
      <td class="txt"><b>${c.symbol}</b><small>${fmtKrw(ref)}</small></td>
      <td style="color:${priceColor(c.kimpUsdtPct)};">${fmtPct(c.kimpUsdtPct)}</td>
      <td style="color:${priceColor(c.kimpFxPct)};">${fmtPct(c.kimpFxPct)}</td>
      <td title="${esc(spreadTitle)}">${fmtPct(spread)}</td>
    </tr>`;
  }).join('') || '<tr><td class="empty" colspan="4">데이터 없음</td></tr>';
  document.querySelectorAll('.arb-list th[data-sort]').forEach(th => th.classList.toggle('sorted', th.dataset.sort === arb.sort.key));
}

function renderKpis() {
  const s = arb.snapshot;
  if (!s) return;
  const fx = s.fx || {};
  const coin = s.coins.find(c => c.symbol === arb.symbol);
  const set = (id, text, color) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (color) el.style.color = color;
  };
  set('kpiSelLabel', `${arb.symbol} 김프 (USDT / 환율)`);
  set('kpiSelUsdt', fmtPct(coin?.kimpUsdtPct), priceColor(coin?.kimpUsdtPct));
  set('kpiSelFx', fmtPct(coin?.kimpFxPct), priceColor(coin?.kimpFxPct));
  const ref = coin?.domesticRef ? coin.prices[coin.domesticRef] : null;
  const glob = coin?.globalRef ? coin.prices[coin.globalRef] : null;
  set('kpiSelPrice', `${exName(coin?.domesticRef)} ${fmtKrw(ref?.krw)} · ${exName(coin?.globalRef)} ${glob?.native != null ? glob.native.toLocaleString('en-US', { maximumFractionDigits: 6 }) : '-'} USDT`);
  set('kpiUsdKrw', fmtKrw(fx.usdKrw ? Math.round(fx.usdKrw * 100) / 100 : null));
  set('kpiUsdKrwAt', fx.usdKrwUpdatedAt ? `기준 ${kstFmt.format(new Date(fx.usdKrwUpdatedAt))} KST` : '환율 조회 실패');
  set('kpiUsdtKrw', fmtKrw(fx.usdtKrw));
  set('kpiUsdtSrc', fx.usdtSource ? `${exName(fx.usdtSource)} KRW-USDT` : '-');
  set('kpiUsdtPrem', fmtPct(fx.usdtPremiumPct), priceColor(fx.usdtPremiumPct));
}

function renderSources() {
  const sources = arb.snapshot?.sources || {};
  const dots = document.getElementById('sourceDots');
  if (dots) {
    dots.innerHTML = ARB_SOURCES.map(code => {
      const st = sources[code]?.status || 'unknown';
      return `<span class="src-dot" data-status="${st}" title="${esc(`${ARB_SOURCE_NAMES[code]}: ${ARB_STATUS_TEXT[st] || st}${sources[code]?.message ? ` — ${sources[code].message}` : ''}`)}"><i aria-hidden="true"></i>${ARB_SOURCE_NAMES[code]}</span>`;
    }).join('');
  }
  const merged = { ...sources, ...(arb.matrix?.sources ? Object.fromEntries(Object.entries(arb.matrix.sources).map(([k, v]) => [`${k} 호가`, v])) : {}), ...(arb.network?.sources || {}) };
  const body = document.getElementById('sourceBody');
  if (body) {
    const fetched = arb.snapshot?.fetchedAt ? kstFmt.format(new Date(arb.snapshot.fetchedAt)) : '-';
    body.innerHTML = Object.entries(merged).map(([code, v]) => {
      const name = code.endsWith(' 호가') ? `${ARB_SOURCE_NAMES[code.replace(' 호가', '')] || code.replace(' 호가', '')} 호가` : (ARB_SOURCE_NAMES[code] || code);
      return `<tr><td class="txt">${esc(name)}</td><td><span class="src-dot" data-status="${esc(v.status)}"><i aria-hidden="true"></i>${esc(ARB_STATUS_TEXT[v.status] || v.status)}</span></td><td class="txt" style="text-align:left;color:var(--muted);">${esc(v.message || '')}</td></tr>`;
    }).join('') + `<tr><td class="txt" colspan="3" style="color:var(--muted);">시세 조회 ${fetched} KST</td></tr>`;
  }
}

function renderExchangePremiums() {
  const s = arb.snapshot;
  const head = document.getElementById('exchangeHead');
  const body = document.getElementById('exchangeBody');
  if (!s || !head || !body) return;
  const krw = Object.keys(s.exchanges).filter(c => s.exchanges[c].quote === 'KRW');
  head.innerHTML = `<tr><th>코인</th>${krw.map(c => `<th>${esc(exName(c))}</th>`).join('')}<th>해외 기준</th></tr>`;
  body.innerHTML = s.coins.map(c => `<tr data-symbol="${c.symbol}" class="${c.symbol === arb.symbol ? 'is-selected' : ''}" style="cursor:pointer;">
    <td class="txt"><b>${c.symbol}</b></td>
    ${krw.map(code => {
      const v = c.premiumUsdtByExchange?.[code];
      return `<td class="cell" style="${heatStyle(v)}" title="${esc(`${exName(code)} ${fmtKrw(c.prices[code]?.krw)}원`)}">${fmtPct(v)}</td>`;
    }).join('')}
    <td class="txt" style="color:var(--muted);">${esc(exName(c.globalRef) || '없음')}</td>
  </tr>`).join('');
}

/* ── 호가 매트릭스·시뮬레이터 ───────────────────────────────────────────── */
function matrixQuery() {
  const params = new URLSearchParams({ sizeKrw: String(arb.sizeKrw) });
  Object.entries(arb.feeOverrides).forEach(([code, v]) => params.set(`fee_${code}`, String(v)));
  if (arb.withdrawOverride != null) params.set('withdrawFee', String(arb.withdrawOverride));
  return params.toString();
}

async function loadMatrix() {
  const seq = ++arbMatrixSeq;
  const symbol = arb.symbol;
  try {
    const data = await arbGet(`/api/arb/${symbol}/matrix?${matrixQuery()}`);
    if (seq !== arbMatrixSeq || symbol !== arb.symbol) return;
    arb.matrix = data;
    renderMatrix();
    renderSimulator();
    renderSources();
  } catch (err) {
    if (seq !== arbMatrixSeq) return;
    document.getElementById('matrixBody').innerHTML = `<tr><td class="empty">호가를 불러오지 못했습니다: ${esc(err.message)}</td></tr>`;
  }
}

function scheduleMatrix() {
  clearTimeout(arbMatrixTimer);
  arbMatrixTimer = setTimeout(loadMatrix, 350);
}

function currentPair() {
  const m = arb.matrix;
  if (!m) return null;
  const want = arb.pick || m.best;
  if (!want) return null;
  return m.pairs.find(p => p.buy === want.buy && p.sell === want.sell) || null;
}

function renderMatrix() {
  const m = arb.matrix;
  const head = document.getElementById('matrixHead');
  const body = document.getElementById('matrixBody');
  if (!m || !head || !body) return;
  const codes = Object.keys(m.books);
  if (codes.length < 2) {
    head.innerHTML = '';
    body.innerHTML = '<tr><td class="empty">비교할 수 있는 호가가 2곳 미만입니다.</td></tr>';
    return;
  }
  const picked = currentPair();
  head.innerHTML = `<tr><th>매수 ↓ / 매도 →</th>${codes.map(c => `<th>${esc(exName(c))}${isGlobal(c) ? '*' : ''}</th>`).join('')}</tr>`;
  body.innerHTML = codes.map(buy => `<tr>
    <td class="txt"><b>${esc(exName(buy))}${isGlobal(buy) ? '*' : ''}</b><small style="display:block;color:var(--muted);font-family:var(--font-mono);font-size:10.5px;">매도호가 ${fmtKrw(m.books[buy].bestAskKrw)}</small></td>
    ${codes.map(sell => {
      if (buy === sell) return '<td class="cell diag">—</td>';
      const p = m.pairs.find(x => x.buy === buy && x.sell === sell);
      if (!p || !p.ok) return `<td class="cell diag" title="${esc(p?.reason || '')}">계산 불가</td>`;
      const cls = ['cell', p.insufficientDepth ? 'thin' : '', picked && picked.buy === buy && picked.sell === sell ? 'picked' : ''].join(' ');
      const tip = `${exName(buy)} 매수 → ${exName(sell)} 매도\n순손익 ${fmtSignedKrw(p.netKrw)} (${fmtPct(p.netPct)})\n호가 차이 ${fmtPct(p.grossPct, 3)}${p.insufficientDepth ? '\n호가 깊이 부족' : ''}`;
      return `<td class="${cls}" style="${heatStyle(p.netPct)}" data-buy="${buy}" data-sell="${sell}" title="${esc(tip)}">${fmtPct(p.netPct)}<small>${fmtPct(p.grossPct, 3)}</small></td>`;
    }).join('')}
  </tr>`).join('');
}

function fillExchangeSelect(el, codes, value) {
  const html = codes.map(c => `<option value="${c}">${esc(exName(c))}${isGlobal(c) ? ' (해외)' : ''}</option>`).join('');
  if (el.dataset.options !== html) {
    el.innerHTML = html;
    el.dataset.options = html;
  }
  if (value) el.value = value;
}

function walletText(state, verb) {
  if (state === 'open') return `${verb} 가능`;
  if (state === 'closed') return `${verb} 중단`;
  return '확인 필요';
}

/**
 * 빗썸 위험 공지 한 건을 경고 줄 HTML로 만든다. 제목·링크는 이스케이프하고, 링크는 빗썸 공지 도메인만 허용한다.
 * @param {object} n matrix 응답의 notices 항목({title, url, publishedAt, kind, coins, probability, by})
 * @returns {string} 경고 줄 HTML
 */
function noticeWarnHtml(n) {
  let link = '';
  try {
    const url = new URL(n.url);
    if (url.origin === 'https://feed.bithumb.com') {
      link = ` <a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer" style="color:var(--info);">원문</a>`;
    }
  } catch { /* 링크가 없거나 형식이 틀리면 제목만 보인다 */ }
  const how = n.by === 'jev' && typeof n.probability === 'number'
    ? `모델 판단 확률 ${Math.round(n.probability * 100)}%`
    : '제목 규칙 판정';
  const target = n.coins === 'UNKNOWN' ? ' · 대상 코인 불명' : '';
  // publishedAt은 KST "yyyy-MM-dd HH:mm:ss". 날짜 없는 중단 공지가 지난 것인지 보이도록 MM/DD HH:mm만 붙인다.
  const t = /^\d{4}-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(n.publishedAt || '');
  const posted = t ? `${t[1]}/${t[2]} ${t[3]}:${t[4]} 게시 · ` : '';
  return `빗썸 공지: ${esc(n.title)} — 확인 필요 (${posted}${how}${target})${link}`;
}

function renderSimulator() {
  const m = arb.matrix;
  if (!m) return;
  const pair = currentPair();
  const codes = Object.keys(m.books);
  const buyEl = document.getElementById('simBuy');
  const sellEl = document.getElementById('simSell');
  fillExchangeSelect(buyEl, codes, pair?.buy || arb.pick?.buy);
  fillExchangeSelect(sellEl, codes, pair?.sell || arb.pick?.sell);

  const active = document.activeElement;
  const setInput = (id, value) => {
    const el = document.getElementById(id);
    if (el && el !== active) el.value = value;
  };
  setInput('simBuyFee', m.fees[buyEl.value] ?? '');
  setInput('simSellFee', m.fees[sellEl.value] ?? '');
  setInput('simWithdraw', arb.withdrawOverride ?? m.transfer.withdrawFee);
  document.getElementById('simWithdrawUnit').textContent = arb.symbol;

  const best = m.best;
  document.getElementById('simBest').innerHTML = best
    ? `최적 경로: <b>${esc(exName(best.buy))} → ${esc(exName(best.sell))}</b> ${fmtPct(best.netPct)}${arb.pick ? ' · <a href="#" id="simUseBest" style="color:var(--info);">최적 경로로 되돌리기</a>' : ''}`
    : '계산 가능한 경로가 없습니다.';

  const set = (id, text, color) => {
    const el = document.getElementById(id);
    el.textContent = text;
    el.style.color = color || '';
  };
  const warn = [];
  if (!pair || !pair.ok || buyEl.value === sellEl.value) {
    ['outBuyAvg', 'outSellAvg', 'outGross', 'outBuyFee', 'outWithdrawFee', 'outSellFee', 'outNet'].forEach(id => set(id, '-'));
    if (buyEl.value === sellEl.value) warn.push('매수·매도 거래소가 같습니다.');
    else if (pair?.reason) warn.push(pair.reason);
  } else {
    set('outBuyAvg', `${fmtKrw(pair.buyAvgKrw)}원`);
    set('outSellAvg', `${fmtKrw(pair.sellAvgKrw)}원`);
    set('outGross', fmtPct(pair.grossPct, 3), priceColor(pair.grossPct));
    set('outBuyFee', fmtSignedKrw(-pair.costs.buyFeeKrw));
    set('outWithdrawFee', fmtSignedKrw(-pair.costs.withdrawFeeKrw));
    set('outSellFee', fmtSignedKrw(-pair.costs.sellFeeKrw));
    set('outNet', `${fmtSignedKrw(pair.netKrw)} (${fmtPct(pair.netPct)})`, priceColor(pair.netKrw));
    if (pair.insufficientDepth) warn.push('호가 깊이가 모자라 일부만 체결되는 계산입니다. 투입 금액을 줄여 보세요.');
    if (isGlobal(pair.buy) || isGlobal(pair.sell)) warn.push('해외 거래소 구간은 USDT를 업비트 KRW-USDT 가격으로 환산했습니다. 원화↔USDT 환전 비용과 해외 송금 규제는 반영하지 않았습니다.');
  }
  const t = m.transfer;
  set('outTransfer', `약 ${t.estimatedMinutes < 1 ? '1분 미만' : `${t.estimatedMinutes}분`} · ${t.network}`);
  const w = `${exName(buyEl.value)} ${walletText(m.wallet[buyEl.value]?.withdraw, '출금')} / ${exName(sellEl.value)} ${walletText(m.wallet[sellEl.value]?.deposit, '입금')}`;
  set('outWallet', w);
  if (m.wallet[buyEl.value]?.withdraw === 'closed' || m.wallet[sellEl.value]?.deposit === 'closed') warn.push('입출금이 중단된 거래소가 포함돼 있어 실제로는 옮길 수 없습니다.');
  // 빗썸 공지는 빗썸이 매수·매도 쪽에 있을 때만 띄운다. 외부 거래소 대상 주의는 그 거래소가 경로에 있을 때만.
  const route = [buyEl.value, sellEl.value];
  const notices = route.includes('BITHUMB')
    ? (m.notices || []).filter(n => n.kind !== 'external' || route.includes(n.exchange))
    : [];
  const lines = [...warn.map(esc), ...notices.map(noticeWarnHtml)];
  const warnEl = document.getElementById('simWarn');
  warnEl.innerHTML = lines.join('<br>');
  warnEl.classList.toggle('show', lines.length > 0);
}

/* ── 김프 추이 차트 ─────────────────────────────────────────────────────── */
function initChart() {
  const el = document.getElementById('premiumChart');
  if (!el || !window.LightweightCharts) return;
  const c = termColors();
  const kstTick = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false });
  const kstDay = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric' });
  arbChart = LightweightCharts.createChart(el, termChartOptions({
    timeScale: {
      timeVisible: true, secondsVisible: false,
      // 축 눈금을 한국 시간으로 표시한다(캔들 시각은 UTC 초).
      tickMarkFormatter: (time, type) => (type <= 2 ? kstDay : kstTick).format(new Date(time * 1000)),
    },
    localization: {
      priceFormatter: p => `${Number(p).toFixed(2)}%`,
      timeFormatter: t => `${kstFmt.format(new Date(t * 1000))} KST`,
    },
    rightPriceScale: { scaleMargins: { top: 0.12, bottom: 0.12 } },
  }));
  arbSeries = arbChart.addBaselineSeries({
    baseValue: { type: 'price', price: 0 },
    topLineColor: c.up, topFillColor1: termAlpha(c.up, 0.28), topFillColor2: termAlpha(c.up, 0.04),
    bottomLineColor: c.down, bottomFillColor1: termAlpha(c.down, 0.04), bottomFillColor2: termAlpha(c.down, 0.28),
    lineWidth: 2,
    priceLineVisible: false,
  });
  arbSeries.createPriceLine({ price: 0, color: c.borderStrong, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '0%' });
  arbChart.subscribeCrosshairMove(param => {
    const hover = document.getElementById('arbHover');
    const p = param?.time != null ? arbPointsByTime.get(param.time) : null;
    hover.textContent = p
      ? `${kstFmt.format(new Date(p.time * 1000))} · ${fmtPct(p.premiumPct)} · 원화 ${fmtKrw(p.krw)} · 해외 ${p.usdt.toLocaleString('en-US', { maximumFractionDigits: 6 })} USDT · USDT ${fmtKrw(p.usdtKrw)}`
      : '';
  });
  new ResizeObserver(() => arbChart && arbChart.resize(el.clientWidth, el.clientHeight)).observe(el);
}

async function loadHistory() {
  const symbol = arb.symbol;
  const interval = arb.interval;
  document.getElementById('chartTitle').textContent = `${symbol} 김프 추이`;
  const note = document.getElementById('chartNote');
  try {
    const data = await arbGet(`/api/arb/${symbol}/history?interval=${interval}`);
    if (symbol !== arb.symbol || interval !== arb.interval) return;
    arb.history = data;
    arbPointsByTime = new Map(data.points.map(p => [p.time, p]));
    if (arbSeries) {
      arbSeries.setData(data.points.map(p => ({ time: p.time, value: p.premiumPct })));
      arbChart.timeScale().fitContent();
    }
    const values = data.points.map(p => p.premiumPct).filter(isNum);
    if (values.length) {
      const avg = values.reduce((a, b) => a + b, 0) / values.length;
      const last = values[values.length - 1];
      note.textContent = `업비트 ${symbol} ÷ (${exName(data.global)} ${symbol}-USDT × 업비트 USDT) − 1 · ${interval === '1H' ? '1시간' : '1일'} 봉 ${values.length}개 · 최근 ${fmtPct(last)} · 평균 ${fmtPct(avg)} · 최고 ${fmtPct(Math.max(...values))} · 최저 ${fmtPct(Math.min(...values))}`;
    } else {
      note.textContent = '겹치는 캔들 구간이 없습니다.';
    }
    document.getElementById('chartSub').textContent = `업비트 ÷ (${exName(data.global)} × 업비트 USDT)`;
  } catch (err) {
    if (symbol === arb.symbol) note.textContent = `추이를 불러오지 못했습니다: ${err.message}`;
  }
}

/* ── 전송·수수료 ────────────────────────────────────────────────────────── */
async function loadNetwork() {
  try {
    arb.network = await arbGet('/api/arb/network');
    renderNetwork();
    renderSources();
  } catch (err) {
    document.getElementById('networkBody').innerHTML = `<tr><td class="empty" colspan="7">불러오지 못했습니다: ${esc(err.message)}</td></tr>`;
  }
}

function renderNetwork() {
  const n = arb.network;
  if (!n) return;
  const priceOf = symbol => {
    const coin = arb.snapshot?.coins.find(c => c.symbol === symbol);
    return coin?.domesticRef ? coin.prices[coin.domesticRef].krw : null;
  };
  document.getElementById('networkBody').innerHTML = n.coins.map(c => {
    const krw = priceOf(c.symbol);
    return `<tr data-symbol="${c.symbol}" class="${c.symbol === arb.symbol ? 'is-selected' : ''}">
      <td class="txt"><b>${c.symbol}</b></td>
      <td class="txt" style="text-align:right;">${esc(c.network)}</td>
      <td>${c.blockSec < 1 ? c.blockSec : Math.round(c.blockSec)}초</td>
      <td>${c.confirmations}</td>
      <td>${c.estimatedMinutes < 1 ? '1분 미만' : `약 ${c.estimatedMinutes}분`}</td>
      <td>${fmtCoin(c.withdrawFee)} ${c.symbol}</td>
      <td>${krw ? `${Math.round(c.withdrawFee * krw).toLocaleString('ko-KR')}원` : '-'}</td>
    </tr>`;
  }).join('');

  const btc = n.coins.find(c => c.symbol === 'BTC');
  const onchain = n.btcOnchainEstimate;
  const btcKrw = priceOf('BTC');
  const noteEl = document.getElementById('btcOnchainNote');
  if (onchain && isNum(onchain.krw) && btc && btcKrw) {
    const exchangeFee = btc.withdrawFee * btcKrw;
    noteEl.innerHTML = `지금 BTC 온체인 수수료(빠름)는 ${onchain.satPerVb} sat/vB × ${onchain.vbytes}vB = ${onchain.sats.toLocaleString('ko-KR')} sat, <b style="color:var(--fg-2);">약 ${onchain.krw.toLocaleString('ko-KR')}원</b>입니다. 거래소 출금 수수료 참고값 ${btc.withdrawFee} BTC(약 ${Math.round(exchangeFee).toLocaleString('ko-KR')}원)는 이 값의 약 ${Math.round(exchangeFee / Math.max(onchain.krw, 1)).toLocaleString('ko-KR')}배입니다. 소액 차익은 대부분 이 고정 수수료 때문에 사라집니다. (출처: mempool.space)`;
  } else {
    noteEl.textContent = 'BTC 온체인 수수료를 불러오지 못했습니다.';
  }

  document.getElementById('feeBody').innerHTML = n.exchanges.map(e => `<tr>
    <td class="txt"><b>${esc(e.name)}</b></td>
    <td>${esc(e.quote)}</td>
    <td>${e.takerFeePct.toFixed(2)}%</td>
    <td class="txt" style="text-align:right;"><a href="${esc(e.feeUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--info);">공식 안내</a></td>
  </tr>`).join('') + `<tr><td class="txt" colspan="4" style="color:var(--muted);">기본 등급 수수료 참고값 · 기준일 ${esc(n.feeReferenceDate)}</td></tr>`;
}

/* ── 선택·이벤트 ────────────────────────────────────────────────────────── */
function selectSymbol(symbol) {
  if (!symbol || symbol === arb.symbol) return;
  arb.symbol = symbol;
  arb.pick = null;
  arb.withdrawOverride = null;
  arb.matrix = null;
  const url = new URL(location.href);
  url.searchParams.set('symbol', symbol);
  history.replaceState(null, '', url);
  renderCoinList();
  renderKpis();
  renderExchangePremiums();
  renderNetwork();
  document.getElementById('matrixBody').innerHTML = '<tr><td class="empty">로딩 중...</td></tr>';
  loadMatrix();
  loadHistory();
}

function bindEvents() {
  document.addEventListener('click', e => {
    const row = e.target.closest('tr[data-symbol]');
    if (row) { selectSymbol(row.dataset.symbol); return; }
    const cell = e.target.closest('td.cell[data-buy]');
    if (cell) {
      arb.pick = { buy: cell.dataset.buy, sell: cell.dataset.sell };
      renderMatrix();
      renderSimulator();
      return;
    }
    if (e.target.id === 'simUseBest') {
      e.preventDefault();
      arb.pick = null;
      renderMatrix();
      renderSimulator();
    }
  });

  document.querySelectorAll('.arb-list th[data-sort]').forEach(th => th.addEventListener('click', () => {
    const key = th.dataset.sort;
    arb.sort = { key, dir: arb.sort.key === key ? -arb.sort.dir : (key === 'symbol' ? 1 : -1) };
    renderCoinList();
  }));

  document.querySelectorAll('#intervalBtns [data-interval]').forEach(btn => btn.addEventListener('click', () => {
    arb.interval = btn.dataset.interval;
    document.querySelectorAll('#intervalBtns [data-interval]').forEach(b => b.classList.toggle('active', b === btn));
    loadHistory();
  }));

  document.querySelectorAll('.term-dock-tab[data-dock]').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.term-dock-tab[data-dock]').forEach(t => {
      t.classList.toggle('active', t === btn);
      t.setAttribute('aria-selected', String(t === btn));
    });
    document.querySelectorAll('.arb-dock-pane').forEach(p => p.classList.toggle('active', p.id === `dock-${btn.dataset.dock}`));
  }));

  const size = document.getElementById('simSize');
  size.addEventListener('input', () => {
    const n = parseNum(size.value);
    if (n == null || n <= 0) return;
    size.value = Math.floor(n).toLocaleString('ko-KR');
    arb.sizeKrw = Math.min(Math.max(Math.floor(n), 10_000), 1_000_000_000);
    scheduleMatrix();
  });

  const onPairChange = () => {
    arb.pick = { buy: document.getElementById('simBuy').value, sell: document.getElementById('simSell').value };
    renderMatrix();
    renderSimulator();
  };
  document.getElementById('simBuy').addEventListener('change', onPairChange);
  document.getElementById('simSell').addEventListener('change', onPairChange);

  const feeInput = (id, selectId) => document.getElementById(id).addEventListener('input', e => {
    const n = parseNum(e.target.value);
    if (n == null || n < 0 || n > 5) return;
    // 수수료를 고치면 그 거래소를 고정 경로로 삼아야 결과가 흔들리지 않는다.
    if (!arb.pick) {
      const pair = currentPair();
      if (pair) arb.pick = { buy: pair.buy, sell: pair.sell };
    }
    arb.feeOverrides[document.getElementById(selectId).value] = n;
    scheduleMatrix();
  });
  feeInput('simBuyFee', 'simBuy');
  feeInput('simSellFee', 'simSell');

  document.getElementById('simWithdraw').addEventListener('input', e => {
    const n = parseNum(e.target.value);
    if (n == null || n < 0) return;
    arb.withdrawOverride = n;
    scheduleMatrix();
  });
}

/* ── 주기 갱신 (화면이 숨겨지면 멈춘다) ─────────────────────────────────── */
let arbFastTimer = null;
let arbSlowTimer = null;

function startPolling() {
  stopPolling();
  arbFastTimer = setInterval(() => { loadSnapshot(); loadMatrix(); }, ARB_FAST_MS);
  arbSlowTimer = setInterval(() => { loadHistory(); loadNetwork(); }, ARB_SLOW_MS);
}

function stopPolling() {
  clearInterval(arbFastTimer);
  clearInterval(arbSlowTimer);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { stopPolling(); return; }
  loadSnapshot();
  loadMatrix();
  startPolling();
});

document.addEventListener('DOMContentLoaded', async () => {
  const wanted = new URLSearchParams(location.search).get('symbol')?.toUpperCase();
  if (wanted && /^[A-Z0-9]{2,10}$/.test(wanted)) arb.symbol = wanted;
  await initPage();
  initChart();
  bindEvents();
  await loadSnapshot();
  if (arb.snapshot && !arb.snapshot.coins.some(c => c.symbol === arb.symbol)) arb.symbol = 'BTC';
  renderKpis();
  loadMatrix();
  loadHistory();
  loadNetwork();
  startPolling();
});
