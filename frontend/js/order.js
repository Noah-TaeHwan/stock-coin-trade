/* ── 상태 ─────────────────────────────────────────────────────────────────── */
let currentMarketCode = 'KRW-BTC';
let currentUser       = null;
let currentPeriod     = 'days';
let selectedExchange  = 'UPBIT';
let priceLinesMap     = {};   // exchange code → LW Charts priceLine

// 거래소 구분 색은 상승·하락 의미색과 겹치지 않게 범주형 팔레트를 쓴다.
const EXCHANGE_META = {
  UPBIT:   { label: '업비트', color: '#4FC3F7', lineStyle: 0 },
  BITHUMB: { label: '빗썸',   color: '#FF9F1A', lineStyle: 1 },
  COINONE: { label: '코인원', color: '#B39DFF', lineStyle: 1 },
  KORBIT:  { label: '코빗',   color: '#FFD60A', lineStyle: 1 },
};
const livePrices = {};   // market code → 최신 WebSocket 체결가

const CRYPTO_WATCH_KEY = 'cryptoWatchlist';
let cryptoWatchlist = new Set(JSON.parse(localStorage.getItem(CRYPTO_WATCH_KEY) || '[]'));

/* ── LW Charts 인스턴스 ──────────────────────────────────────────────────── */
let lwChart     = null;
let lwCandle    = null;
let lwVolume    = null;

function initLwChart() {
  const container = document.getElementById('coinChart');
  if (!container || !window.LightweightCharts) return;

  lwChart = LightweightCharts.createChart(container, termChartOptions({
    timeScale:  { timeVisible: true, secondsVisible: false },
    handleScroll: true,
    handleScale:  true,
  }));

  lwCandle = lwChart.addCandlestickSeries(termCandleColors());

  lwVolume = lwChart.addHistogramSeries({
    color:      termAlpha(termColors().info, 0.3),
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  // v4에서는 거래량 축 여백을 가격 축 옵션으로 지정해야 캔들과 겹치지 않는다.
  lwChart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

  new ResizeObserver(() => {
    if (lwChart && container) lwChart.resize(container.clientWidth, container.clientHeight);
  }).observe(container);
}

/* ── Upbit 캔들 fetch ────────────────────────────────────────────────────── */
async function loadCoinChart(marketCode, period) {
  if (!lwCandle) return;
  const symbol = marketCode.split('-')[1];

  const upbitUrls = {
    'days':       `/upbit-api/candles/days?market=${marketCode}&count=200`,
    'weeks':      `/upbit-api/candles/weeks?market=${marketCode}&count=100`,
    'minutes/1':  `/upbit-api/candles/minutes/1?market=${marketCode}&count=200`,
    'minutes/60': `/upbit-api/candles/minutes/60?market=${marketCode}&count=200`,
  };
  const url = upbitUrls[period] ?? upbitUrls['days'];

  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (!Array.isArray(data)) return;

    const candles = data.map(d => ({
      time:  Math.floor(new Date(d.candle_date_time_utc).getTime() / 1000),
      open:  d.opening_price,
      high:  d.high_price,
      low:   d.low_price,
      close: d.trade_price,
    })).sort((a, b) => a.time - b.time);

    const volumes = data.map(d => ({
      time:  Math.floor(new Date(d.candle_date_time_utc).getTime() / 1000),
      value: d.candle_acc_trade_volume,
      color: termAlpha(d.trade_price >= d.opening_price ? termColors().up : termColors().down, 0.35),
    })).sort((a, b) => a.time - b.time);

    // 코인마다 가격 단위가 달라 마지막 종가로 소수 자릿수를 정한다.
    const last = candles[candles.length - 1]?.close ?? 0;
    const precision = last >= 100 ? 0 : last >= 1 ? 2 : 4;
    lwCandle.applyOptions({ priceFormat: { type: 'price', precision, minMove: 1 / 10 ** precision } });
    lwCandle.setData(candles);
    lwVolume.setData(volumes);
    lwChart.timeScale().fitContent();
  } catch {}
}

/* ── 기간 버튼 ───────────────────────────────────────────────────────────── */
document.getElementById('coinPeriodBtns')?.addEventListener('click', async (e) => {
  const btn = e.target.closest('.period-btn');
  if (!btn) return;
  currentPeriod = btn.dataset.period;
  document.querySelectorAll('#coinPeriodBtns .period-btn').forEach(b =>
    b.classList.toggle('active', b === btn));
  await loadCoinChart(currentMarketCode, currentPeriod);
});

/* ── 초기화 ──────────────────────────────────────────────────────────────── */
(async () => {
  currentUser = await initPage();

  initLwChart();
  const [marketRes] = await Promise.all([apiFetch('/api/crypto/market-list')]);
  if (!marketRes.ok) return;
  const { markets, marketCodes } = await marketRes.json();

  // 명령줄(CRY BTC, KRW-ETH)에서 넘어온 코인이 원화 마켓에 있으면 그 코인으로 시작한다.
  const requested = new URLSearchParams(location.search).get('market')?.trim().toUpperCase();
  if (requested && markets.some(m => m.market === requested)) currentMarketCode = requested;

  renderMarketSidebar(markets);
  initWebSocket(marketCodes);
  await getCryptoInfo(currentMarketCode);
  await loadCoinChart(currentMarketCode, currentPeriod);
  updateAssetDisplay();
  startOrderbookPolling();
  loadCoinAccount();
  setInterval(loadCoinAccount, 15_000);
  setInterval(renderCoinHoldings, 3_000);
})();

/* ── 마켓 사이드바 렌더 ──────────────────────────────────────────────────── */
function renderMarketSidebar(markets) {
  const tbody = document.getElementById('marketListBody');
  if (!tbody) return;
  tbody.innerHTML = markets.map(m => {
    const market = escapeHtml(m.market);
    const name = escapeHtml(m.koreanName);
    return `
    <tr onclick="selectCoin(${jsArg(m.market)})" data-market="${market}"${m.market === currentMarketCode ? ' class="is-selected"' : ''}>
      <td class="txt">${name}<small>${escapeHtml(String(m.market).replace('KRW-', ''))}</small></td>
      <td id="${market}-trade_price">-</td>
      <td id="${market}-signed_change_rate">-</td>
      <td style="text-align:center;" onclick="event.stopPropagation()">
        <button id="${market}-watch-btn" class="cry-watch" onclick="toggleCryptoWatch(${jsArg(m.market)})" aria-label="${name} 관심 표시">☆</button>
      </td>
    </tr>`;
  }).join('');
  renderCryptoWatchBtns();
}

async function selectCoin(marketCode) {
  currentMarketCode = marketCode;
  document.querySelectorAll('#marketListBody tr[data-market]').forEach(row => row.classList.toggle('is-selected', row.dataset.market === marketCode));
  await getCryptoInfo(marketCode);
  await loadCoinChart(marketCode, currentPeriod);
  loadOrderbook();
}

/* ── 업비트 웹소켓 ───────────────────────────────────────────────────────── */
function initWebSocket(marketCodes) {
  const socket = new WebSocket(upbitWebSocketUrl());
  socket.onopen = () => {
    socket.send(JSON.stringify([
      { ticket: 'portfolio-order' },
      { type: 'ticker', codes: marketCodes },
    ]));
  };
  socket.onmessage = async (e) => {
    try {
      const r     = JSON.parse(await e.data.text());
      if (r.type !== 'ticker') return;
      const code  = r.code;
      const price = new Intl.NumberFormat('ko-KR').format(r.trade_price);
      let   rate  = (r.signed_change_rate * 100).toFixed(2);
      const color = priceColor(rate);
      if (rate > 0) rate = '+' + rate;
      livePrices[code] = r.trade_price;

      const tEl = document.getElementById(code + '-trade_price');
      const rEl = document.getElementById(code + '-signed_change_rate');
      if (tEl) { tEl.textContent = price; tEl.style.color = color; }
      if (rEl) { rEl.textContent = rate + '%'; rEl.style.color = color; }

      if (code === currentMarketCode) {
        const lp = document.getElementById('crypto_live_price');
        const lr = document.getElementById('crypto_live_rate');
        if (lp) { lp.textContent = price; lp.style.color = color; }
        if (lr) { lr.textContent = rate + '%'; lr.style.color = color; }
        setText('crypto_high', new Intl.NumberFormat('ko-KR').format(r.high_price));
        setText('crypto_low', new Intl.NumberFormat('ko-KR').format(r.low_price));
        setText('crypto_vol24', `${new Intl.NumberFormat('ko-KR').format(Math.round(r.acc_trade_price_24h / 1e8))}억`);
      }

      // acc_trade_price_24h는 ticker에서 생략 (표시 공간 절약)
    } catch {}
  };
  socket.onerror = () => console.warn('웹소켓 연결 실패');
}

/* ── 코인 정보 + 국내 시세 ───────────────────────────────────────────────── */
let domesticTimer = null;
let selectedDomesticCode = 'KRW-BTC';
const exchangeCodes = ['UPBIT','BITHUMB','COINONE','KORBIT'];
let domPriceMap = {};

async function getCryptoInfo(marketCode) {
  currentMarketCode = marketCode;
  const res = await apiFetch('/api/crypto/' + marketCode);
  if (!res.ok) return;
  const data = await res.json();
  const sym = data.marketCode?.split('-')[1] ?? 'BTC';

  setText('crypto_korean_name', data.koreanName ?? '-');
  setText('crypto_symbol_name', data.marketCode ?? '-');
  setText('buy_symbol_name',    `${data.koreanName}(${sym})`);
  setText('sell_symbol_name',   `${data.koreanName}(${sym})`);
  setText('holdCryptoCount',    data.buyCryptoCount ?? 0);
  setText('holdCryptoSymbol',   sym);

  startDomesticPolling(marketCode);
}

function startDomesticPolling(marketCode) {
  selectedDomesticCode = marketCode;
  domPriceMap = {};
  renderInlineDomesticBar();
  fetchDomesticPrices(marketCode);
  if (domesticTimer) clearInterval(domesticTimer);
  domesticTimer = setInterval(() => fetchDomesticPrices(selectedDomesticCode), 5000);
}

async function fetchDomesticPrices(code) {
  try {
    const res  = await apiFetch('/api/crypto/' + encodeURIComponent(code) + '/domestic-prices');
    const data = await res.json();
    setText('domestic_price_symbol', data.symbol ?? 'BTC');
    setText('domestic_price_updated_at', '갱신 ' + (data.fetchedAt ? new Date(data.fetchedAt).toLocaleTimeString('ko-KR',{hour12:false}) : '-'));
    domPriceMap = {};
    (data.prices ?? []).forEach(p => { domPriceMap[p.exchangeCode] = p.tradePriceKrw; });
    renderInlineDomesticBar();
    updateChartPriceLines();
    updateSelectedExchangeDisplay();
  } catch {}
}

/* 거래소 인라인 바 렌더 */
function renderInlineDomesticBar() {
  exchangeCodes.forEach(code => {
    const cell = document.getElementById('domestic-price-' + code);
    const item = document.querySelector(`.dom-inline-item[data-exchange="${code}"]`);
    const p = domPriceMap[code];
    if (cell) cell.textContent = p != null ? new Intl.NumberFormat('ko-KR').format(p) : '-';
    if (item) item.classList.toggle('selected', code === selectedExchange);
  });
}

/* 선택 거래소 현재가 업데이트 */
function updateSelectedExchangeDisplay() {
  const meta  = EXCHANGE_META[selectedExchange] ?? EXCHANGE_META.UPBIT;
  const price = domPriceMap[selectedExchange];
  setText('selectedExchangeLabel', meta.label);
  const el = document.getElementById('selectedExchangePrice');
  if (el) {
    el.textContent = price != null ? new Intl.NumberFormat('ko-KR').format(price) : '-';
    el.style.color = meta.color;
  }
}

/* 차트에 거래소별 가격선 오버레이 */
function updateChartPriceLines() {
  if (!lwCandle) return;
  // 기존 가격선 제거
  Object.values(priceLinesMap).forEach(pl => { try { lwCandle.removePriceLine(pl); } catch {} });
  priceLinesMap = {};

  // 각 거래소 가격선 추가 (Upbit 제외 — 캔들 자체가 Upbit)
  exchangeCodes.forEach(code => {
    const price = domPriceMap[code];
    if (price == null || price <= 0) return;
    const meta  = EXCHANGE_META[code] ?? {};
    const isSelected = code === selectedExchange;
    priceLinesMap[code] = lwCandle.createPriceLine({
      price,
      color:            meta.color,
      lineWidth:        isSelected ? 2 : 1,
      lineStyle:        isSelected ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: isSelected,
      title:            isSelected ? meta.label : '',
    });
  });
}

/* 거래소 탭 클릭 핸들러 */
document.getElementById('exchangeTabs')?.addEventListener('click', e => {
  const btn = e.target.closest('.exchange-tab');
  if (!btn) return;
  selectedExchange = btn.dataset.exchange;
  document.querySelectorAll('.exchange-tab').forEach(b => b.classList.toggle('active', b === btn));
  renderInlineDomesticBar();
  updateChartPriceLines();
  updateSelectedExchangeDisplay();
});

/* 인라인 바 클릭으로도 거래소 선택 */
document.addEventListener('click', e => {
  const item = e.target.closest('.dom-inline-item');
  if (!item) return;
  const code = item.dataset.exchange;
  if (!code) return;
  selectedExchange = code;
  document.querySelectorAll('.exchange-tab').forEach(b => b.classList.toggle('active', b.dataset.exchange === code));
  renderInlineDomesticBar();
  updateChartPriceLines();
  updateSelectedExchangeDisplay();
});

/* ── 보유자산 표시 ───────────────────────────────────────────────────────── */
async function updateAssetDisplay() {
  const el = document.getElementById('holdAsset');
  if (!el) return;
  const user = currentUser ?? await getCurrentUser();
  if (user?.loggedIn) {
    el.textContent = new Intl.NumberFormat('ko-KR').format(user.asset);
  } else {
    const disp = document.getElementById('buyAssetDisplay');
    if (disp) disp.innerHTML = '<span style="font-size:12px;color:var(--muted);">로그인 필요</span>';
    el.textContent = '0';
  }
}

/* ── 퍼센트 버튼 ─────────────────────────────────────────────────────────── */
document.querySelectorAll('#buyQuantityBtnGroup > button').forEach(btn =>
  btn.addEventListener('click', () => {
    const asset = parseInt(document.getElementById('holdAsset').textContent.replaceAll(',', '')) || 0;
    const pct   = parseInt(btn.textContent) / 100;
    document.getElementById('buyKrw').value = new Intl.NumberFormat('ko-KR').format(Math.floor(asset * pct));
  })
);
document.querySelectorAll('#sellQuantityBtnGroup > button').forEach(btn =>
  btn.addEventListener('click', () => {
    const count = parseFloat(document.getElementById('holdCryptoCount').textContent) || 0;
    const pct   = parseInt(btn.textContent) / 100;
    document.getElementById('sellCount').value = Math.round(count * pct * 1e8) / 1e8;
  })
);

/* ── 매수 ────────────────────────────────────────────────────────────────── */
async function submitBuy() {
  if (!currentUser?.loggedIn) { location.href = '/member/login.html'; return; }
  clearOrderErrors();
  const res  = await apiFetch('/api/trade/order/buy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ marketCode: currentMarketCode, buyKrw: document.getElementById('buyKrw').value }),
  });
  const data = await res.json();
  if (res.ok) {
    document.getElementById('holdAsset').textContent = new Intl.NumberFormat('ko-KR').format(data.asset);
    document.getElementById('buyKrw').value = '';
    await getCryptoInfo(currentMarketCode);
    loadCoinAccount();
  } else {
    showOrderError('buyError', data.error ?? '매수 실패');
  }
}

/* ── 매도 ────────────────────────────────────────────────────────────────── */
async function submitSell() {
  if (!currentUser?.loggedIn) { location.href = '/member/login.html'; return; }
  clearOrderErrors();
  const res  = await apiFetch('/api/trade/order/sell', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ marketCode: currentMarketCode, sellCount: document.getElementById('sellCount').value }),
  });
  const data = await res.json();
  if (res.ok) {
    document.getElementById('holdAsset').textContent = new Intl.NumberFormat('ko-KR').format(data.asset);
    document.getElementById('sellCount').value = '';
    await getCryptoInfo(currentMarketCode);
    loadCoinAccount();
  } else {
    showOrderError('sellError', data.error ?? '매도 실패');
  }
}

function clearOrderErrors() {
  ['buyError','sellError'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.style.display = 'none'; el.textContent = ''; }
  });
}
function showOrderError(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.display = 'block'; }
}

/* ── 관심종목 ────────────────────────────────────────────────────────────── */
function saveCryptoWatchlist() { localStorage.setItem(CRYPTO_WATCH_KEY, JSON.stringify([...cryptoWatchlist])); }
function renderCryptoWatchBtns() {
  cryptoWatchlist.forEach(code => {
    const btn = document.getElementById(code + '-watch-btn');
    if (btn) { btn.textContent = '★'; btn.style.color = 'var(--warn)'; }
  });
}
function toggleCryptoWatch(code) {
  const btn = document.getElementById(code + '-watch-btn');
  if (cryptoWatchlist.has(code)) {
    cryptoWatchlist.delete(code);
    if (btn) { btn.textContent = '☆'; btn.style.color = 'var(--muted)'; }
  } else {
    cryptoWatchlist.add(code);
    if (btn) { btn.textContent = '★'; btn.style.color = 'var(--warn)'; }
  }
  saveCryptoWatchlist();
}

/* ── 주문 티켓 탭 (매수 / 매도) ──────────────────────────────────────────── */
document.querySelectorAll('.ticket-tab').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.ticket-tab').forEach(t => {
    t.classList.toggle('active', t === btn);
    t.setAttribute('aria-selected', String(t === btn));
  });
  document.querySelectorAll('.ticket-pane').forEach(pane => pane.classList.toggle('active', pane.id === `ticket-${btn.dataset.side}`));
}));

/* ── 하단 도크 탭 (보유 / 체결) ──────────────────────────────────────────── */
document.querySelectorAll('.term-dock-tab[data-dock]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.term-dock-tab[data-dock]').forEach(t => {
    t.classList.toggle('active', t === btn);
    t.setAttribute('aria-selected', String(t === btn));
  });
  document.querySelectorAll('.cry-dock-pane').forEach(pane => pane.classList.toggle('active', pane.id === `dock-${btn.dataset.dock}`));
}));

/* ── 업비트 호가 사다리 (2초 폴링) ───────────────────────────────────────── */
const fmtCoin = n => Number(n).toLocaleString('ko-KR', { maximumFractionDigits: Number(n) >= 100 ? 0 : 4 });

async function loadOrderbook() {
  const code = currentMarketCode;
  try {
    const res = await fetch(`/upbit-api/orderbook?markets=${encodeURIComponent(code)}`);
    if (!res.ok || code !== currentMarketCode) return;
    const units = (await res.json())?.[0]?.orderbook_units?.slice(0, 8) ?? [];
    if (!units.length) return;
    const maxSize = Math.max(...units.flatMap(u => [u.ask_size, u.bid_size]));
    const row = (price, size, side) => `<tr class="${side}">
      <td style="text-align:left;color:var(--fg-2);"><span class="bar" style="width:${(size / maxSize * 100).toFixed(1)}%;"></span>${Number(size).toFixed(4)}</td>
      <td class="px">${fmtCoin(price)}</td></tr>`;
    document.getElementById('coinAskBody').innerHTML = [...units].reverse().map(u => row(u.ask_price, u.ask_size, 'ask')).join('');
    document.getElementById('coinBidBody').innerHTML = units.map(u => row(u.bid_price, u.bid_size, 'bid')).join('');
    const spread = units[0].ask_price - units[0].bid_price;
    setText('coinBookLast', fmtCoin(livePrices[code] ?? units[0].bid_price));
    setText('coinBookSpread', `${fmtCoin(spread)} (${(spread / units[0].bid_price * 100).toFixed(3)}%)`);
  } catch {}
}

function startOrderbookPolling() {
  loadOrderbook();
  setInterval(loadOrderbook, 2_000);
}

/* ── 보유 코인 · 체결 내역 도크 ──────────────────────────────────────────── */
let lastCoinHoldings = null;

async function loadCoinAccount() {
  if (!currentUser?.loggedIn) {
    const guest = '<tr><td class="empty" colspan="7">로그인하면 보유 코인과 체결 내역을 볼 수 있습니다.</td></tr>';
    document.getElementById('coinHoldingsBody').innerHTML = guest;
    document.getElementById('coinHistoryBody').innerHTML = guest;
    return;
  }
  try {
    const res = await apiFetch('/api/trade/hold');
    if (res.ok) { lastCoinHoldings = (await res.json()).holdCryptoList ?? []; renderCoinHoldings(); }
  } catch {}
  try {
    const res = await apiFetch('/api/trade/order/history?limit=30');
    if (!res.ok) return;
    const history = (await res.json()).history ?? [];
    document.getElementById('coinHistoryBody').innerHTML = history.length ? history.map(h => {
      const isBuy = h.type === 'BUY';
      return `<tr>
        <td style="color:var(--muted);">${new Date(h.ts).toLocaleString('ko-KR', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</td>
        <td class="txt"><strong>${escapeHtml(h.koreanName)}</strong> <span style="color:var(--accent);font-family:var(--font-mono);font-size:11px;">${escapeHtml(String(h.marketCode).replace('KRW-', ''))}</span></td>
        <td style="font-weight:800;color:${isBuy ? 'var(--up)' : 'var(--down)'};">${isBuy ? 'BUY 매수' : 'SELL 매도'}</td>
        <td>${fmtCoin(h.price)}</td>
        <td style="color:var(--fg-2);">${Number(h.quantity).toFixed(8)}</td>
        <td>${Number(h.amount).toLocaleString('ko-KR')}</td>
      </tr>`;
    }).join('') : '<tr><td class="empty" colspan="6">체결 내역이 없습니다.</td></tr>';
  } catch {}
}

function renderCoinHoldings() {
  const tbody = document.getElementById('coinHoldingsBody');
  if (!tbody || !lastCoinHoldings) return;
  if (!lastCoinHoldings.length) { tbody.innerHTML = '<tr><td class="empty" colspan="7">보유 코인이 없습니다.</td></tr>'; return; }
  tbody.innerHTML = lastCoinHoldings.map(h => {
    const price = livePrices[h.marketCode];
    const evalKrw = price ? price * h.holdCount : null;
    // 원 단위·소수 둘째 자리로 먼저 반올림해 -0, -0.00%가 보이지 않게 한다.
    const pnl = evalKrw != null ? Math.round(evalKrw - h.buyTotalKrw) || 0 : null;
    const rate = pnl != null && h.buyTotalKrw ? Math.round(pnl / h.buyTotalKrw * 10000) / 100 || 0 : null;
    const color = priceColor(pnl ?? 0);
    return `<tr onclick="selectCoin(${jsArg(h.marketCode)})" style="cursor:pointer;">
      <td class="txt"><strong>${escapeHtml(h.koreanName)}</strong> <span style="color:var(--accent);font-family:var(--font-mono);font-size:11px;">${escapeHtml(h.marketCodeOnlySymbol)}</span></td>
      <td>${Number(h.holdCount).toFixed(8)}</td>
      <td style="color:var(--fg-2);">${fmtCoin(h.buyAverage)}</td>
      <td>${price ? fmtCoin(price) : '-'}</td>
      <td>${evalKrw != null ? Math.round(evalKrw).toLocaleString('ko-KR') : '-'}</td>
      <td style="color:${color};">${pnl != null ? `${pnl > 0 ? '+' : ''}${pnl.toLocaleString('ko-KR')}` : '-'}</td>
      <td style="color:${color};">${rate != null ? `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%` : '-'}</td>
    </tr>`;
  }).join('');
}

/* ── 유틸 ────────────────────────────────────────────────────────────────── */
function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
