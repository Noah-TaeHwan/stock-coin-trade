/* ── 상태 ─────────────────────────────────────────────────────────────────── */
let currentPeriod       = '1m';
let currentMarketFilter = 'ALL';
let allStocks           = [];
let lastPositions       = [];
let lastCash            = 100_000_000;
let liveStockPrices     = {};
let watchlist           = new Set(JSON.parse(localStorage.getItem('stockWatchlist') || '[]'));
let stockPickerActiveIndex = -1;
let stockPickerMatches = [];
let stockPickerRequestId = 0;
let currentStockPrice = 0;
// 종목 목록(/api/stocks/list)이 코드순 30개만 반환해 삼성전자 등 대형주가 빠질 수 있으므로,
// 기본 종목은 검색 API에 의존하지 않고 아래 객체를 allStocks에 직접 주입해 항상 보장한다.
let DEFAULT_STOCK_SYMBOL = '005930';
let defaultStockCandidate = { symbol: '005930', name: '삼성전자', market: 'KOSPI', sector: '반도체·IT' };

async function pickTopVolumeKospiSymbol() {
  try {
    const data = await requestJson('/api/stocks/prices');
    const quotes = Object.values(data.prices ?? {});
    const top = quotes
      .filter(q => q.market === 'KOSPI' && Number(q.volume) > 0)
      .sort((a, b) => Number(b.volume) - Number(a.volume))[0];
    if (top?.symbol) {
      DEFAULT_STOCK_SYMBOL = top.symbol;
      defaultStockCandidate = { symbol: top.symbol, name: top.name, market: top.market, sector: top.sector || '기타' };
    }
  } catch {}
}

/* ── LW Charts ───────────────────────────────────────────────────────────── */
let lwChart  = null;
let lwCandle = null;
let lwVolume = null;
const movingAverageSeries = {};
const movingAverageOptions = [
  { period: 5,   color: '#FFD60A' },
  { period: 20,  color: '#4FC3F7' },
  { period: 60,  color: '#B39DFF' },
  { period: 120, color: '#FF6FAE' },
];
const movingAverageVisibility = Object.fromEntries(movingAverageOptions.map(({ period }) => [period, true]));

function toggleMovingAverage(period) {
  if (!movingAverageSeries[period]) return;
  movingAverageVisibility[period] = !movingAverageVisibility[period];
  movingAverageSeries[period].applyOptions({ visible: movingAverageVisibility[period] });

  const button = document.querySelector(`.ma-toggle[data-ma-period="${period}"]`);
  button?.classList.toggle('active', movingAverageVisibility[period]);
  button?.setAttribute('aria-pressed', String(movingAverageVisibility[period]));
}

function calculateMovingAverage(candles, period) {
  let total = 0;
  return candles.reduce((values, candle, index) => {
    total += candle.close;
    if (index >= period) total -= candles[index - period].close;
    if (index >= period - 1) values.push({ time: candle.time, value: total / period });
    return values;
  }, []);
}

function initStockChart() {
  const container = document.getElementById('stockChart');
  if (!container || !window.LightweightCharts) return;

  lwChart = LightweightCharts.createChart(container, termChartOptions({
    timeScale:  { timeVisible: true, secondsVisible: false },
    handleScroll: true, handleScale: true,
  }));

  lwCandle = lwChart.addCandlestickSeries({ ...termCandleColors(), priceFormat: { type: 'price', precision: 0, minMove: 1 } });

  lwVolume = lwChart.addHistogramSeries({
    color: termAlpha(termColors().info, 0.3),
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  // v4에서는 거래량 축 여백을 가격 축 옵션으로 지정해야 캔들과 겹치지 않는다.
  lwChart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

  movingAverageOptions.forEach(({ period, color }) => {
    movingAverageSeries[period] = lwChart.addLineSeries({
      color,
      lineWidth: 2,
      visible: movingAverageVisibility[period],
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });
  });

  new ResizeObserver(() => {
    if (lwChart && container) lwChart.resize(container.clientWidth, container.clientHeight);
  }).observe(container);
}

/* ── 포트폴리오 도넛 (미니) ─────────────────────────────────────────────── */
let portfolioChart = null;

function initPortfolioChart() {
  const el = document.getElementById('portfolioChart');
  if (!el || !window.LightweightCharts) return;
  // ApexCharts 미사용 시 간단히 생략 — 필요 시 별도 라이브러리 추가
}

function updatePortfolioMini(positions, cash) {
  const el = document.getElementById('portfolioChart');
  if (!el) return;
  const total = cash + positions.reduce((s, p) => s + (p.evalAmount || 0), 0);
  if (total <= 0) { el.innerHTML = ''; return; }

  const cashPct = Math.round(cash / total * 100);
  const colors = TERM_PALETTE;
  const stockBars = positions.map((p, i) => {
    const pct = Math.round((p.evalAmount || 0) / total * 100);
    return `<div title="${escapeHtml(p.name)} ${pct}%" style="flex:${pct};background:${colors[i % colors.length]};min-width:3px;"></div>`;
  });
  stockBars.push(`<div title="현금 ${cashPct}%" style="flex:${cashPct};background:#5B616C;min-width:3px;"></div>`);

  const sectors = positions.reduce((acc, p) => {
    const sector = p.sector || '기타';
    acc[sector] = (acc[sector] || 0) + (p.evalAmount || 0);
    return acc;
  }, {});
  const sectorItems = Object.entries(sectors).sort((a, b) => b[1] - a[1]);
  const sectorBars = sectorItems.map(([sector, amount], i) => {
    const pct = Math.round(amount / total * 100);
    return `<div title="${escapeHtml(sector)} ${pct}%" style="flex:${pct};background:${colors[i % colors.length]};min-width:3px;"></div>`;
  });
  if (cashPct) sectorBars.push(`<div title="현금 ${cashPct}%" style="flex:${cashPct};background:#5B616C;min-width:3px;"></div>`);
  const sectorLabels = sectorItems.map(([sector, amount], i) =>
    `<span style="display:inline-flex;align-items:center;gap:3px;"><i style="width:6px;height:6px;background:${colors[i % colors.length]};display:inline-block;"></i>${escapeHtml(sector)} ${Math.round(amount / total * 100)}%</span>`
  ).join(' · ');

  el.innerHTML = `<div style="font-size:11px;font-weight:700;color:var(--muted);margin-top:6px;">종목별 비중</div>
    <div style="display:flex;height:7px;overflow:hidden;gap:1px;margin-top:3px;">${stockBars.join('')}</div>
    <div style="font-size:11px;font-weight:700;color:var(--muted);margin-top:6px;">섹터별 비중</div>
    <div style="display:flex;height:7px;overflow:hidden;gap:1px;margin-top:3px;">${sectorBars.join('')}</div>
    <div style="font-size:11px;line-height:1.6;color:var(--muted);margin-top:4px;">${sectorLabels || '보유 주식 없음'}${sectorLabels ? ` · 현금 ${cashPct}%` : ''}</div>`;
}

/* ── 포맷터 ──────────────────────────────────────────────────────────────── */
function fmtKrw(v) { return Number(v).toLocaleString('ko-KR') + '원'; }
function fmtVol(v) {
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '억주';
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '만주';
  return Number(v).toLocaleString('ko-KR') + '주';
}
function colorByVal(v) { return priceColor(v); }

function selectedPosition() {
  const symbol = document.getElementById('stockSymbol')?.value;
  return lastPositions.find(position => position.symbol === symbol);
}

function updateOrderSummary() {
  const summary = document.getElementById('orderSummary');
  const qty = Number(document.getElementById('orderQty')?.value) || 0;
  if (!summary) return;
  const position = selectedPosition();
  const holdingQty = position?.quantity ?? 0;
  const orderAmount = currentStockPrice > 0 && qty > 0 ? currentStockPrice * qty : 0;
  summary.innerHTML = `보유 현금 <strong style="color:var(--fg);">${fmtKrw(lastCash)}</strong> · 보유 주식 <strong style="color:var(--fg);">${holdingQty.toLocaleString('ko-KR')}주</strong><br>예상 주문금액 <strong style="color:var(--accent-dark);">${orderAmount ? fmtKrw(orderAmount) : '-'}</strong>`;
}

function setOrderQuantityByPercent(side, percent) {
  if (!currentStockPrice) { showMsg('현재 시세를 불러온 뒤 선택해주세요.', true); return; }
  const position = selectedPosition();
  const quantity = side === 'buy'
    ? Math.floor(lastCash * (percent / 100) / currentStockPrice)
    : Math.floor((position?.quantity ?? 0) * (percent / 100));
  if (quantity < 1) {
    showMsg(side === 'buy' ? '보유 현금으로 매수 가능한 수량이 없습니다.' : '매도 가능한 보유 수량이 없습니다.', true);
    return;
  }
  const input = document.getElementById('orderQty');
  if (input) input.value = quantity;
  updateOrderSummary();
}

/* ── 물타기 계산기 (시뮬레이션 전용) ─────────────────────────────────────── */
function avgDownPosition() {
  const position = selectedPosition();
  return position && Number(position.pnl) < 0 ? position : null;
}

function setAvgDownModalOpen(open) {
  const modal = document.getElementById('avgDownModal');
  if (!modal) return;
  modal.classList.toggle('open', open);
  modal.setAttribute('aria-hidden', String(!open));
  if (open) document.getElementById('avgDownQty')?.focus();
}

function renderAvgDownCalculator() {
  const position = avgDownPosition();
  const content = document.getElementById('avgDownContent');
  const unavailable = document.getElementById('avgDownUnavailable');
  const subtitle = document.getElementById('avgDownSubtitle');
  if (!content || !unavailable || !subtitle) return;

  if (!position || currentStockPrice <= 0) {
    content.style.display = 'none';
    unavailable.style.display = 'block';
    unavailable.textContent = currentStockPrice <= 0
      ? '현재 시세를 불러온 뒤 다시 시도해주세요.'
      : '현재 선택한 종목의 손익이 마이너스인 보유 포지션에서만 계산할 수 있습니다.';
    subtitle.textContent = '손실 상태의 보유 종목을 선택하면 추가 매수 시 평균단가 변화를 계산합니다.';
    return;
  }

  content.style.display = '';
  unavailable.style.display = 'none';
  const pnlRate = ((currentStockPrice - Number(position.avgPrice)) / Number(position.avgPrice)) * 100;
  subtitle.textContent = `${position.name} (${position.symbol}) · 실제 주문은 실행되지 않는 시뮬레이션입니다.`;
  setText('avgDownHolding', `${Number(position.quantity).toLocaleString('ko-KR')}주 · ${fmtKrw(position.avgPrice)}`);
  setEl('avgDownCurrent', `${fmtKrw(currentStockPrice)} · ${pnlRate.toFixed(2)}%`, colorByVal(pnlRate));
  updateAvgDownResult();
}

function updateAvgDownResult() {
  const position = avgDownPosition();
  if (!position || currentStockPrice <= 0) return;
  const qty = Math.floor(Number(document.getElementById('avgDownQty')?.value) || 0);
  const cost = qty > 0 ? currentStockPrice * qty : 0;
  const isAffordable = cost <= lastCash;
  const totalQty = Number(position.quantity) + qty;
  const newAvg = qty > 0 ? Math.round((Number(position.avgPrice) * Number(position.quantity) + cost) / totalQty) : Number(position.avgPrice);
  const avgDiff = newAvg - Number(position.avgPrice);

  setText('avgDownCost', cost ? fmtKrw(cost) : '-');
  setText('avgDownNewAvg', qty > 0 ? fmtKrw(newAvg) : '-');
  setEl('avgDownDiff', qty > 0 ? `${avgDiff > 0 ? '+' : ''}${fmtKrw(avgDiff)}` : '-', colorByVal(avgDiff));
  setEl('avgDownCashLeft', qty > 0 ? fmtKrw(lastCash - cost) : fmtKrw(lastCash), isAffordable ? undefined : 'var(--down)');

  const notice = document.getElementById('avgDownNotice');
  if (!notice) return;
  if (!qty) {
    notice.textContent = `보유 현금 ${fmtKrw(lastCash)} 내에서 수량 또는 비율을 선택하세요.`;
    notice.style.color = 'var(--muted)';
  } else if (!isAffordable) {
    notice.textContent = `추가 매수금액이 보유 현금보다 ${fmtKrw(cost - lastCash)} 큽니다.`;
    notice.style.color = 'var(--down)';
  } else {
    const breakEvenGap = Math.max(0, newAvg - currentStockPrice);
    notice.textContent = `현재가가 새 평균단가까지 ${fmtKrw(breakEvenGap)} (${((breakEvenGap / currentStockPrice) * 100).toFixed(2)}%) 오르면 손익분기점입니다.`;
    notice.style.color = 'var(--muted)';
  }
}

function openAvgDownCalculator() {
  renderAvgDownCalculator();
  setAvgDownModalOpen(true);
}

function setAvgDownQuantityByPercent(percent) {
  if (!currentStockPrice) return;
  const qty = Math.floor(lastCash * (percent / 100) / currentStockPrice);
  const input = document.getElementById('avgDownQty');
  if (input) input.value = qty || '';
  updateAvgDownResult();
}

/* ── API fetch helper ────────────────────────────────────────────────────── */
async function requestJson(url, options = {}) {
  const fullUrl  = url.startsWith('/') ? API_BASE + url : url;
  const response = await fetch(fullUrl, { credentials: 'include', ...options });
  const raw = await response.text();
  let data = null;
  try { data = raw.trim() ? JSON.parse(raw) : null; } catch { throw new Error('응답 형식 오류'); }
  if (!response.ok) throw new Error(data?.message || '요청 실패');
  if (data === null) throw new Error('빈 응답');
  return data;
}

function showMsg(msg, isErr = false) {
  const el = document.getElementById('stockMessage');
  if (el) { el.textContent = msg; el.style.color = isErr ? 'var(--down)' : 'var(--up)'; }
}

/* ── Watchlist ───────────────────────────────────────────────────────────── */
function saveWatchlist() { localStorage.setItem('stockWatchlist', JSON.stringify([...watchlist])); }
function updateWatchBtn(sym) {
  const btn = document.getElementById('watchlistBtn');
  if (!btn) return;
  const has = watchlist.has(sym);
  btn.textContent = has ? '⭐' : '☆';
  btn.style.color = has ? 'var(--warn)' : 'var(--muted)';
}
document.getElementById('watchlistBtn')?.addEventListener('click', () => {
  const sym = document.getElementById('stockSymbol')?.value;
  if (!sym) return;
  watchlist.has(sym) ? watchlist.delete(sym) : watchlist.add(sym);
  saveWatchlist(); updateWatchBtn(sym);
  renderStockWatchList();
});

/* ── 마켓 리스트 (실시간 5초 polling) ───────────────────────────────────── */
async function loadBatchPrices() {
  try {
    const symbols = allStocks.slice(0, 50).map(stock => stock.symbol).join(',');
    const data = await requestJson(`/api/stocks/prices?symbols=${encodeURIComponent(symbols)}`);
    liveStockPrices = data.prices ?? {};
    renderStockMarketList();
  } catch {}
}

function renderStockMarketList() {
  const tbody = document.getElementById('stockMarketListBody');
  if (!tbody) return;

  renderStockWatchList();
  const selectedSymbol = document.getElementById('stockSymbol')?.value;
  if (!lastPositions.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="3">보유 중인 종목이 없습니다.</td></tr>`;
    return;
  }

  tbody.innerHTML = lastPositions.map(position => {
    const pnl = Number(position.pnl ?? 0);
    const color = colorByVal(pnl);
    return `<tr onclick="selectStockFromList(${jsArg(position.symbol)})"${position.symbol === selectedSymbol ? ' class="is-selected"' : ''}>
      <td class="txt">${escapeHtml(position.name)}<small>${escapeHtml(position.symbol)}</small></td>
      <td>${Number(position.quantity).toLocaleString('ko-KR')}</td>
      <td style="color:${color};">${pnl >= 0 ? '+' : ''}${Number(pnl).toLocaleString('ko-KR')}</td>
    </tr>`;
  }).join('');
}

// TWS 관심목록처럼 선택 종목과 연결된 목록. 전체는 종목 목록, 관심은 ☆ 표시 종목이다.
function renderStockWatchList() {
  const tbody = document.getElementById('stockWatchListBody');
  if (!tbody) return;
  const selectedSymbol = document.getElementById('stockSymbol')?.value;
  const rows = currentMarketFilter === 'WATCH'
    ? allStocks.filter(stock => watchlist.has(stock.symbol))
    : allStocks;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="3">${currentMarketFilter === 'WATCH' ? '☆로 관심종목을 추가하세요.' : '종목 정보 없음'}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(stock => {
    const live = liveStockPrices[stock.symbol] ?? {};
    const rate = Number(live.changeRate ?? 0);
    const color = colorByVal(rate);
    return `<tr onclick="selectStockFromList(${jsArg(stock.symbol)})"${stock.symbol === selectedSymbol ? ' class="is-selected"' : ''}>
      <td class="txt">${escapeHtml(stock.name)}<small>${escapeHtml(stock.symbol)}${watchlist.has(stock.symbol) ? ' ★' : ''}</small></td>
      <td style="color:${color};">${live.price ? Number(live.price).toLocaleString('ko-KR') : '-'}</td>
      <td style="color:${color};">${live.price ? `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%` : '-'}</td>
    </tr>`;
  }).join('');
}

function toggleStockWatch(sym) {
  watchlist.has(sym) ? watchlist.delete(sym) : watchlist.add(sym);
  saveWatchlist();
  renderStockMarketList();
  updateWatchBtn(sym);
}

async function selectStockFromList(sym) {
  await selectStock(sym);
}

/* ── 종목 검색·선택 ─────────────────────────────────────────────────────── */
async function loadStockList() {
  const data = await requestJson('/api/stocks/list?limit=30');
  allStocks = data.stocks ?? [];
  const explicitSymbol = new URLSearchParams(window.location.search).get('symbol')?.trim().toUpperCase();
  const targetSymbol = explicitSymbol || DEFAULT_STOCK_SYMBOL;

  if (targetSymbol && !allStocks.some(stock => stock.symbol === targetSymbol)) {
    if (!explicitSymbol && defaultStockCandidate?.symbol === targetSymbol) {
      // 검색 API 없이도 기본 종목이 항상 목록에 포함되도록 직접 주입한다.
      addStockToPicker(defaultStockCandidate);
    } else {
      try {
        const search = await requestJson(`/api/stocks/search?q=${encodeURIComponent(targetSymbol)}&limit=20`);
        const found = (search.stocks ?? []).find(stock => stock.symbol === targetSymbol);
        if (found) addStockToPicker(found);
      } catch {}
    }
  }
  rebuildSelectOptions();
  if (targetSymbol && allStocks.some(stock => stock.symbol === targetSymbol)) {
    const select = document.getElementById('stockSymbol');
    if (select) select.value = targetSymbol;
    updateStockPickerSelected(targetSymbol);
  }
}


function addStockToPicker(stock) {
  if (!stock?.symbol || allStocks.some(item => item.symbol === stock.symbol)) return;
  allStocks.push(stock);
}

async function fetchStockPickerMatches(query = '') {
  const keyword = String(query).trim();
  if (!keyword) return allStocks.slice(0, 12);
  const data = await requestJson(`/api/stocks/search?q=${encodeURIComponent(keyword)}&limit=20`);
  return data.stocks ?? [];
}

function updateStockPickerSelected(symbol) {
  const stock = allStocks.find(item => item.symbol === symbol);
  const input = document.getElementById('stockPickerInput');
  const label = document.getElementById('stockPickerSelected');
  if (!stock) return;
  if (input) input.value = stock.name;
  if (label) label.textContent = `${stock.symbol} · ${stock.market} · ${stock.sector || '기타'}`;
}

function closeStockPicker() {
  const results = document.getElementById('stockSearchResults');
  const input = document.getElementById('stockPickerInput');
  if (results) results.classList.remove('open');
  if (input) {
    input.setAttribute('aria-expanded', 'false');
    updateStockPickerSelected(document.getElementById('stockSymbol')?.value);
  }
  stockPickerActiveIndex = -1;
}

function renderStockPickerResults() {
  const results = document.getElementById('stockSearchResults');
  const input = document.getElementById('stockPickerInput');
  if (!results || !input) return;
  const matches = stockPickerMatches;
  if (stockPickerActiveIndex >= matches.length) stockPickerActiveIndex = matches.length - 1;

  results.innerHTML = matches.length
    ? matches.map((stock, index) => `<button type="button" class="stock-picker-result${index === stockPickerActiveIndex ? ' active' : ''}" role="option" aria-selected="${stock.symbol === document.getElementById('stockSymbol')?.value}" data-symbol="${escapeHtml(stock.symbol)}">
        <span><strong class="stock-picker-result-name">${escapeHtml(stock.name)}</strong><small class="stock-picker-result-meta">${escapeHtml(stock.market)} · ${escapeHtml(stock.sector || '기타')}</small></span>
        <code class="stock-picker-result-code">${escapeHtml(stock.symbol)}</code>
      </button>`).join('')
    : '<div class="stock-picker-empty">일치하는 종목이 없습니다.</div>';
  results.classList.add('open');
  input.setAttribute('aria-expanded', 'true');
}

async function searchStockPicker(query = document.getElementById('stockPickerInput')?.value ?? '') {
  const requestId = ++stockPickerRequestId;
  try {
    const matches = await fetchStockPickerMatches(query);
    if (requestId !== stockPickerRequestId) return [];
    matches.forEach(addStockToPicker);
    stockPickerMatches = matches;
    if (stockPickerActiveIndex >= matches.length) stockPickerActiveIndex = matches.length - 1;
    renderStockPickerResults();
    return matches;
  } catch (error) {
    if (requestId !== stockPickerRequestId) return [];
    stockPickerMatches = [];
    const results = document.getElementById('stockSearchResults');
    if (results) {
      results.innerHTML = `<div class="stock-picker-empty">${escapeHtml(error.message || 'KRX 종목 검색을 사용할 수 없습니다.')}</div>`;
      results.classList.add('open');
    }
    return [];
  }
}

async function selectStock(symbol) {
  const select = document.getElementById('stockSymbol');
  if (!select) return;
  const stock = allStocks.find(item => item.symbol === symbol);
  if (!stock) return;
  if (!Array.from(select.options).some(option => option.value === symbol)) {
    const option = document.createElement('option');
    option.value = symbol;
    option.textContent = `${stock.name} · ${stock.sector || '기타'} (${symbol})`;
    select.appendChild(option);
  }
  select.value = symbol;
  updateStockPickerSelected(symbol);
  closeStockPicker();
  updateWatchBtn(symbol);
  renderStockMarketList();
  await Promise.all([loadQuote(symbol), loadChart(symbol, currentPeriod)]);
}

function rebuildSelectOptions() {
  renderStockMarketList();
  const sel = document.getElementById('stockSymbol');
  if (!sel) return;
  const prevVal  = sel.value;
  sel.innerHTML  = '';

  if (!allStocks.length) {
    const opt = document.createElement('option');
    opt.disabled = true;
    opt.textContent = '종목 정보 없음';
    sel.appendChild(opt);
    return;
  }

  const markets = [...new Set(allStocks.map(s => s.market))];
  markets.forEach(market => {
    const grp = document.createElement('optgroup');
    grp.label = market;
    allStocks.filter(s => s.market === market).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.symbol;
      opt.textContent = `${s.name} · ${s.sector || '기타'} (${s.symbol})`;
      if (s.symbol === prevVal) opt.selected = true;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  });

  sel.value = allStocks.some(s => s.symbol === prevVal)
    ? prevVal
    : (allStocks.some(s => s.symbol === DEFAULT_STOCK_SYMBOL) ? DEFAULT_STOCK_SYMBOL : allStocks[0].symbol);
  updateStockPickerSelected(sel.value);
}

/* ── 종목 모니터 탭 (전체 / 관심) ───────────────────────────────────────── */
document.querySelectorAll('.wl-tab').forEach(btn => btn.addEventListener('click', () => {
  currentMarketFilter = btn.dataset.wl;
  document.querySelectorAll('.wl-tab').forEach(t => {
    t.classList.toggle('active', t === btn);
    t.setAttribute('aria-selected', String(t === btn));
  });
  renderStockWatchList();
}));

/* ── 하단 도크 탭 (포지션 / 체결 / 시세·계좌) ────────────────────────────── */
document.querySelectorAll('.term-dock-tab[data-dock]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.term-dock-tab[data-dock]').forEach(t => {
    t.classList.toggle('active', t === btn);
    t.setAttribute('aria-selected', String(t === btn));
  });
  document.querySelectorAll('.stk-dock-pane').forEach(pane => pane.classList.toggle('active', pane.id === `dock-${btn.dataset.dock}`));
}));

/* ── 차트 로드 ───────────────────────────────────────────────────────────── */
async function loadChart(symbol, period) {
  if (!lwCandle) return;
  try {
    const data = await requestJson(`/api/stocks/chart?symbol=${encodeURIComponent(symbol)}&period=${encodeURIComponent(period)}&include_ma=1`);
    const candles = (data.data ?? []).map(d => ({ time: Math.floor(d.x / 1000), open: d.o, high: d.h, low: d.l, close: d.c }))
      .sort((a, b) => a.time - b.time);
    const volumes = (data.data ?? []).map(d => ({
      time: Math.floor(d.x / 1000), value: d.v,
      color: termAlpha(d.c >= d.o ? termColors().up : termColors().down, 0.35),
    })).sort((a, b) => a.time - b.time);
    lwCandle.setData(candles);
    lwVolume.setData(volumes);
    movingAverageOptions.forEach(({ period }) => {
      movingAverageSeries[period]?.setData(calculateMovingAverage(candles, period));
    });
    const visibleFrom = data.visibleFrom ? Math.floor(data.visibleFrom / 1000) : null;
    if (visibleFrom && candles.length) {
      lwChart.timeScale().setVisibleRange({ from: visibleFrom, to: candles[candles.length - 1].time });
    } else {
      lwChart.timeScale().fitContent();
    }
  } catch {}
}

/* ── 시세 조회 ───────────────────────────────────────────────────────────── */
async function loadQuote(symbol) {
  if (!symbol) return;
  try {
    const data = await requestJson(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
    const rate  = Number(data.changeRate ?? 0);
    const color = colorByVal(rate);
    currentStockPrice = Number(data.price ?? 0);

    setText('chartStockName',  data.name ?? '-');
    setText('secCode',         `${symbol} ${data.market === 'KOSDAQ' ? 'KQ' : 'KS'} EQUITY`);
    setEl('quotePrice',        fmtKrw(data.price ?? 0), color);
    setEl('quoteChange',       (Number(data.change ?? 0) >= 0 ? '+' : '') + fmtKrw(data.change ?? 0), color);
    setEl('quoteChangeRate',   (rate >= 0 ? '+' : '') + rate.toFixed(2) + '%', color);
    setText('quoteVolume',     data.volume ? fmtVol(data.volume) : '-');
    setText('quoteMarket',     data.market ?? '-');
    if (data.simulated) document.getElementById('dataSourceBadge')?.classList.remove('hidden');
    else                document.getElementById('dataSourceBadge')?.classList.add('hidden');

    renderOrderBook(data.price);
    updateBreakEven(lastPositions, symbol);
    updateWatchBtn(symbol);
    updateOrderSummary();
    if (document.getElementById('avgDownModal')?.classList.contains('open')) renderAvgDownCalculator();

    // 라이브 가격 업데이트
    liveStockPrices[symbol] = { ...liveStockPrices[symbol], price: data.price, changeRate: rate };
    renderStockMarketList();
  } catch {}
}

/* ── 시장 지수 ───────────────────────────────────────────────────────────── */
async function loadMarket() {
  try {
    const data = await requestJson('/api/stocks/market');
    for (const [key, val] of Object.entries({ KOSPI: data.KOSPI, KOSDAQ: data.KOSDAQ })) {
      const p = key.toLowerCase();
      setText(p + 'Price', Number(val.price).toLocaleString('ko-KR', { minimumFractionDigits: 2 }));
      const rate  = Number(val.changeRate);
      const color = colorByVal(rate);
      setEl(p + 'Change', `${rate > 0 ? '▲' : rate < 0 ? '▼' : '■'} ${Math.abs(rate).toFixed(2)}%`, color);
    }
  } catch {}
}

/* ── 계좌 + 포지션 ───────────────────────────────────────────────────────── */
async function loadAccount() {
  const data = await requestJson('/api/stocks/account');
  lastCash = data.cash;
  setText('accountCash',   fmtKrw(data.cash));
  setText('accountAsset',  fmtKrw(data.totalAsset));
  const pnl = Number(data.totalPnlRate);
  setEl('accountPnlRate', (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + '%', colorByVal(pnl));
  updatePortfolioMini(lastPositions, data.cash);
  updateOrderSummary();
}

async function loadPositions() {
  const data = await requestJson('/api/stocks/positions');
  lastPositions = data.positions ?? [];
  const tbody = document.getElementById('positionsBody');
  if (!tbody) return;

  if (!lastPositions.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="6">포지션 없음</td></tr>`;
    renderStockMarketList();
    updatePortfolioMini([], lastCash);
    updateOrderSummary();
    return;
  }
  tbody.innerHTML = lastPositions.map(pos => {
    const pnl   = Number(pos.pnl ?? 0);
    const color = colorByVal(pnl);
    return `<tr onclick="selectStockFromList(${jsArg(pos.symbol)})" style="cursor:pointer;">
      <td class="txt"><strong>${escapeHtml(pos.name)}</strong> <span style="color:var(--accent);font-family:var(--font-mono);font-size:11px;">${escapeHtml(pos.symbol)}</span></td>
      <td class="txt" style="color:var(--muted);">${escapeHtml(pos.sector || '기타')}</td>
      <td>${Number(pos.quantity).toLocaleString('ko-KR')}</td>
      <td style="color:var(--fg-2);">${fmtKrw(pos.avgPrice)}</td>
      <td>${fmtKrw(pos.evalAmount)}</td>
      <td style="font-weight:700;color:${color};">${pnl >= 0 ? '+' : ''}${fmtKrw(pnl)}</td>
    </tr>`;
  }).join('');
  renderStockMarketList();
  updatePortfolioMini(lastPositions, lastCash);
  updateBreakEven(lastPositions, document.getElementById('stockSymbol')?.value);
  updateOrderSummary();
  if (document.getElementById('avgDownModal')?.classList.contains('open')) renderAvgDownCalculator();
}

async function loadHistory() {
  try {
    const data = await requestJson('/api/stocks/orders/history');
    const tbody = document.getElementById('historyBody');
    if (!tbody) return;
    const hist = (data.history ?? []).slice(0, 30);
    if (!hist.length) {
      tbody.innerHTML = `<tr><td class="empty" colspan="5">거래 내역 없음</td></tr>`;
      return;
    }
    tbody.innerHTML = hist.map(h => {
      const isBuy = h.type === 'BUY';
      const color = isBuy ? 'var(--up)' : 'var(--down)';
      const dt    = new Date(h.ts).toLocaleTimeString('ko-KR', { hour12: false });
      return `<tr>
        <td style="color:var(--muted);">${dt}</td>
        <td class="txt"><strong>${escapeHtml(h.name)}</strong> <span style="color:var(--accent);font-family:var(--font-mono);font-size:11px;">${escapeHtml(h.symbol)}</span></td>
        <td style="font-weight:800;color:${color};">${isBuy ? 'BUY 매수' : 'SELL 매도'}</td>
        <td style="color:var(--fg-2);">${Number(h.quantity).toLocaleString('ko-KR')}주</td>
        <td>${fmtKrw(h.amount)}</td>
      </tr>`;
    }).join('');
  } catch {}
}

/* ── 호가창 ──────────────────────────────────────────────────────────────── */
function renderOrderBook(price) {
  if (!price || price <= 0) return;
  const askBody = document.getElementById('askBody');
  const bidBody = document.getElementById('bidBody');
  if (!askBody || !bidBody) return;

  let tick = 1;
  if      (price >= 500000) tick = 1000;
  else if (price >= 100000) tick = 500;
  else if (price >=  50000) tick = 100;
  else if (price >=  10000) tick = 50;
  else if (price >=   1000) tick = 10;

  const qty = (p, o) => Math.max(50, ((p * 7 + o) % 2900) + 100);
  const askRows = Array.from({ length: 5 }, (_, i) => ({ price: price + tick * (i + 1), qty: qty(price + tick * (i + 1), 13) }));
  const bidRows = Array.from({ length: 5 }, (_, i) => ({ price: price - tick * (5 - i), qty: qty(price - tick * (5 - i), 31) }));

  // 사다리는 위에서부터 매도 호가(높은 가격) → 현재가 → 매수 호가(낮은 가격) 순이다.
  const maxQty = Math.max(...askRows.map(r => r.qty), ...bidRows.map(r => r.qty));
  const ladderRow = (r, side) => `<tr class="${side}">
    <td style="text-align:left;color:var(--fg-2);"><span class="bar" style="width:${(r.qty / maxQty * 100).toFixed(1)}%;"></span>${Number(r.qty).toLocaleString('ko-KR')}</td>
    <td class="px">${Number(r.price).toLocaleString('ko-KR')}</td></tr>`;
  askBody.innerHTML = [...askRows].reverse().map(r => ladderRow(r, 'ask')).join('');
  bidBody.innerHTML = [...bidRows].reverse().map(r => ladderRow(r, 'bid')).join('');

  setText('obCurrentPrice', Number(price).toLocaleString('ko-KR'));
  const spread = tick * 2;
  setText('obSpread', `${Number(spread).toLocaleString('ko-KR')} (${((spread / price) * 100).toFixed(3)}%)`);
}

function updateBreakEven(positions, sym) {
  const el = document.getElementById('quoteBreakEven');
  if (!el) return;
  const pos = positions?.find(p => p.symbol === sym);
  if (pos) { el.textContent = `${Number(pos.avgPrice).toLocaleString('ko-KR')}원`; el.style.color = 'var(--warn)'; }
  else      { el.textContent = '-'; el.style.color = 'var(--muted)'; }
}

/* ── 주문 ────────────────────────────────────────────────────────────────── */
async function submitOrder(type) {
  const qty = Number(document.getElementById('orderQty')?.value);
  if (!Number.isFinite(qty) || qty <= 0) { showMsg('수량은 1 이상이어야 합니다.', true); return; }
  try {
    await requestJson(`/api/stocks/orders/${type}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: document.getElementById('stockSymbol')?.value, quantity: qty }),
    });
    showMsg(`${type === 'buy' ? '매수' : '매도'} 완료`);
    await Promise.all([loadAccount(), loadPositions(), loadQuote(document.getElementById('stockSymbol')?.value), loadHistory()]);
  } catch (e) { showMsg(e.message, true); }
}

document.getElementById('buyBtn')?.addEventListener('click',  () => submitOrder('buy'));
document.getElementById('sellBtn')?.addEventListener('click', () => submitOrder('sell'));
document.getElementById('orderQty')?.addEventListener('input', updateOrderSummary);
document.querySelectorAll('.order-percent-btn[data-order-side]').forEach(button => {
  button.addEventListener('click', () => setOrderQuantityByPercent(button.dataset.orderSide, Number(button.dataset.percent)));
});
document.getElementById('avgDownBtn')?.addEventListener('click', openAvgDownCalculator);
document.getElementById('avgDownCloseBtn')?.addEventListener('click', () => setAvgDownModalOpen(false));
document.getElementById('avgDownQty')?.addEventListener('input', updateAvgDownResult);
document.querySelectorAll('.avgdown-percent-btn').forEach(button => {
  button.addEventListener('click', () => setAvgDownQuantityByPercent(Number(button.dataset.percent)));
});
document.getElementById('avgDownModal')?.addEventListener('click', event => {
  if (event.target.id === 'avgDownModal') setAvgDownModalOpen(false);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.getElementById('avgDownModal')?.classList.contains('open')) setAvgDownModalOpen(false);
});

/* ── 초기화 버튼 ─────────────────────────────────────────────────────────── */
document.getElementById('resetBtn')?.addEventListener('click', async () => {
  if (!confirm('계좌를 초기화하시겠습니까?')) return;
  try {
    await requestJson('/api/stocks/account/reset', { method: 'POST' });
    showMsg('계좌 초기화 완료');
    await Promise.all([loadAccount(), loadPositions(), loadHistory()]);
  } catch (e) { showMsg(e.message, true); }
});

/* ── 기간 버튼 ───────────────────────────────────────────────────────────── */
document.getElementById('periodBtns')?.addEventListener('click', async e => {
  const btn = e.target.closest('.period-btn');
  if (!btn) return;
  currentPeriod = btn.dataset.period;
  document.querySelectorAll('#periodBtns .period-btn').forEach(b => b.classList.toggle('active', b === btn));
  await loadChart(document.getElementById('stockSymbol')?.value, currentPeriod);
});

/* ── 종목 변경 ───────────────────────────────────────────────────────────── */
document.getElementById('stockSymbol')?.addEventListener('change', async () => {
  const sym = document.getElementById('stockSymbol')?.value;
  if (!sym) return;
  updateStockPickerSelected(sym);
  await Promise.all([loadQuote(sym), loadChart(sym, currentPeriod)]);
});

/* ── 검색형 종목 선택기 ─────────────────────────────────────────────────── */
const stockPickerInput = document.getElementById('stockPickerInput');
const stockPickerResults = document.getElementById('stockSearchResults');

stockPickerInput?.addEventListener('focus', () => {
  stockPickerActiveIndex = -1;
  searchStockPicker(stockPickerInput.value);
  stockPickerInput.select();
});

stockPickerInput?.addEventListener('input', () => {
  stockPickerActiveIndex = -1;
  searchStockPicker(stockPickerInput.value);
});

stockPickerInput?.addEventListener('keydown', async event => {
  const matches = stockPickerMatches;
  if (event.key === 'Escape') {
    event.preventDefault();
    closeStockPicker();
    stockPickerInput.blur();
    return;
  }
  if (!matches.length || !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
  event.preventDefault();
  if (event.key === 'ArrowDown') {
    stockPickerActiveIndex = (stockPickerActiveIndex + 1) % matches.length;
    renderStockPickerResults();
  } else if (event.key === 'ArrowUp') {
    stockPickerActiveIndex = (stockPickerActiveIndex - 1 + matches.length) % matches.length;
    renderStockPickerResults();
  } else {
    await selectStock(matches[Math.max(stockPickerActiveIndex, 0)].symbol);
  }
});

async function submitStockPickerSearch() {
  if (!stockPickerInput) return;
  const matches = await searchStockPicker(stockPickerInput.value);
  if (!stockPickerInput.value.trim()) {
    stockPickerActiveIndex = -1;
    renderStockPickerResults();
    stockPickerInput.focus();
    return;
  }
  if (matches.length === 1) {
    await selectStock(matches[0].symbol);
    return;
  }
  stockPickerActiveIndex = matches.length ? 0 : -1;
  renderStockPickerResults();
  stockPickerInput.focus();
}

document.getElementById('stockPickerSearch')?.addEventListener('click', submitStockPickerSearch);

stockPickerResults?.addEventListener('click', async event => {
  const option = event.target.closest('[data-symbol]');
  if (option) await selectStock(option.dataset.symbol);
});

document.getElementById('stockPickerClear')?.addEventListener('click', async () => {
  if (!stockPickerInput) return;
  stockPickerInput.value = '';
  stockPickerInput.focus();
  stockPickerActiveIndex = -1;
  await searchStockPicker('');
});

document.addEventListener('click', event => {
  if (!event.target.closest('#stockPicker')) closeStockPicker();
});

/* ── 유틸 ────────────────────────────────────────────────────────────────── */
function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function setEl(id, val, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  if (color) el.style.color = color;
}

/* ── 부트 ────────────────────────────────────────────────────────────────── */
(async () => {
  await initPage();
  initStockChart();

  await pickTopVolumeKospiSymbol();
  await loadStockList();

  const sym = document.getElementById('stockSymbol')?.value;
  await Promise.all([loadMarket(), loadQuote(sym), loadAccount(), loadPositions()]);
  await Promise.all([loadChart(sym, currentPeriod), loadHistory(), loadBatchPrices()]);

  // 명령줄에서 종목명으로 넘어온 경우(?q=) 검색 결과를 바로 연다.
  const query = new URLSearchParams(window.location.search).get('q')?.trim();
  if (query && stockPickerInput) {
    stockPickerInput.value = query;
    await submitStockPickerSearch();
  }

  // 실시간 갱신
  setInterval(() => loadBatchPrices(),  5_000);
  setInterval(() => {
    const s = document.getElementById('stockSymbol')?.value;
    if (s) loadQuote(s);
  }, 5_000);
  setInterval(() => {
    loadMarket();
    loadAccount();
    loadPositions();
  }, 15_000);
  setInterval(() => loadHistory(), 30_000);
})();
