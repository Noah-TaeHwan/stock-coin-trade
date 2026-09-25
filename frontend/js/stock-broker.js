// 주식 화면 하단 도크의 "KIS·KB 원본"과 "메모" 탭.
// 옛 HTS 시뮬레이터(hts.html)에서 옮긴 기능이다. 증권사 API는 조회만 하고 주문은 하지 않는다.
(() => {
  const $ = id => document.getElementById(id);
  const fmt = n => Number(n).toLocaleString('ko-KR');
  const esc = text => String(text ?? '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const BROKERS = { kis: 'KIS Testbed', kb: 'KB증권 Open API' };
  const MEMO_LIMIT = 500;
  let user = null;
  const memos = {};

  const currentSymbol = () => $('stockSymbol')?.value || '';
  const stockName = symbol => (typeof allStocks !== 'undefined' ? allStocks : []).find(s => s.symbol === symbol)?.name || symbol;

  /* ── KIS·KB 원본 조회 ─────────────────────────────────────────────── */
  const toNumber = value => {
    const number = Number(String(value ?? '').replace(/[,%]/g, ''));
    return Number.isFinite(number) ? number : 0;
  };
  // KB 응답은 TR마다 필드 이름이 달라 후보 이름을 깊이 우선으로 찾는다.
  function kbValue(raw, names) {
    const stack = [raw];
    while (stack.length) {
      const item = stack.pop();
      if (!item || typeof item !== 'object') continue;
      for (const [key, value] of Object.entries(item)) {
        if (names.includes(key.toLowerCase()) && value !== '') return value;
        if (value && typeof value === 'object') stack.push(value);
      }
    }
    return undefined;
  }
  function normalizeQuote(broker, data) {
    if (broker === 'kis') return data.quote || {};
    const raw = data.quote?.raw || {};
    return {
      price: kbValue(raw, ['now_prc', 'cur_prc', 'stck_prpr', 'price', 'close_prc']),
      change: kbValue(raw, ['bdy_cmpr', 'prdy_vrss', 'chg_prc', 'change']),
      changeRate: kbValue(raw, ['up_dwn_r_p2', 'prdy_ctrt', 'chg_rt', 'change_rate']),
      volume: kbValue(raw, ['acml_vlm', 'acml_vol', 'acc_vol', 'volume']),
    };
  }
  function normalizeOrderbook(broker, data) {
    if (broker === 'kis') return data.orderbook?.levels || [];
    const raw = data.result?.raw || {};
    return Array.from({ length: 10 }, (_, i) => {
      const n = i + 1;
      return { askPrice: raw[`s${n}_aprc`], askQty: raw[`s_pstn_s${n}_aprc_q`], bidPrice: raw[`b${n}_aprc`], bidQty: raw[`b_pstn_b${n}_aprc_q`] };
    }).filter(level => level.askPrice || level.bidPrice);
  }
  const candlesOf = data => data.chart?.candles || data.result?.candles || [];

  function logExchange(broker, path, status, ok, body) {
    const log = $('brokerLog');
    if (!log) return;
    log.querySelector('.brk-empty')?.remove();
    const entry = document.createElement('article');
    entry.className = 'brk-entry';
    const time = new Date().toLocaleTimeString('ko-KR', { hour12: false });
    entry.innerHTML = `<header><b>${broker.toUpperCase()}</b><span>${time}</span><span class="${ok ? 'ok' : 'err'}">HTTP ${status}</span><code></code></header><pre></pre>`;
    entry.querySelector('code').textContent = `GET ${path}`;
    let pretty = body;
    try { pretty = JSON.stringify(JSON.parse(body), null, 2); } catch (_) {}
    entry.querySelector('pre').textContent = pretty;
    log.prepend(entry);
    while (log.children.length > 20) log.lastElementChild.remove();
  }

  async function getBroker(broker, path) {
    const response = await fetch(path, { credentials: 'include' });
    const body = await response.text();
    logExchange(broker, path, response.status, response.ok, body);
    let data;
    try { data = JSON.parse(body); } catch (_) { throw new Error('증권사 API가 JSON이 아닌 응답을 반환했습니다.'); }
    if (!response.ok || !data.ok) throw new Error(data.message || `증권사 API 요청에 실패했습니다(HTTP ${response.status}).`);
    return data;
  }

  function renderSummary(rows) {
    $('brokerSummary').innerHTML = rows.map(([label, value, cls]) => `<dt>${label}</dt><dd${cls ? ` class="${cls}"` : ''}>${value}</dd>`).join('');
  }

  async function refreshBroker(broker) {
    const symbol = currentSymbol();
    if (!symbol) return;
    const buttons = document.querySelectorAll('[data-broker]');
    buttons.forEach(b => { b.disabled = true; b.classList.toggle('term-btn-primary', b.dataset.broker === broker); });
    const status = $('brokerStatus');
    status.textContent = `${BROKERS[broker]} · ${stockName(symbol)}(${symbol}) 조회 중…`;
    const base = `/api/broker-test/${broker}`;
    const q = `symbol=${encodeURIComponent(symbol)}`;
    try {
      const quote = normalizeQuote(broker, await getBroker(broker, `${base}/quote?${q}`));
      const levels = normalizeOrderbook(broker, await getBroker(broker, `${base}/orderbook?${q}`));
      const candles = candlesOf(await getBroker(broker, `${base}/chart?${q}`));
      const rate = toNumber(quote.changeRate);
      const best = levels[0] || {};
      renderSummary([
        ['출처', BROKERS[broker]],
        ['종목', `${esc(stockName(symbol))} <small>${symbol}</small>`],
        ['현재가', quote.price ? fmt(toNumber(quote.price)) : '-'],
        ['등락률', quote.changeRate != null ? `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%` : '-', rate > 0 ? 'up' : rate < 0 ? 'down' : 'flat'],
        ['거래량', quote.volume ? fmt(toNumber(quote.volume)) : '-'],
        ['최우선 매도', best.askPrice ? `${fmt(toNumber(best.askPrice))} × ${fmt(toNumber(best.askQty))}` : '-', 'down'],
        ['최우선 매수', best.bidPrice ? `${fmt(toNumber(best.bidPrice))} × ${fmt(toNumber(best.bidQty))}` : '-', 'up'],
        ['호가 단계', `${levels.length}단계`],
        ['일봉', `${candles.length}개`],
      ]);
      status.textContent = `${BROKERS[broker]} 시세·호가·일봉 조회 완료 — 앱 모의 시세와 값이 다를 수 있습니다.`;
    } catch (error) {
      status.textContent = `${BROKERS[broker]} 연결 확인 필요: ${error.message}`;
    } finally {
      buttons.forEach(b => { b.disabled = false; });
    }
  }

  /* ── 종목 메모(로그인 회원별) ─────────────────────────────────────── */
  function syncMemo() {
    const symbol = currentSymbol();
    const area = $('memoText');
    if (!area) return;
    $('memoTarget').textContent = symbol ? `${stockName(symbol)} (${symbol})` : '-';
    area.value = memos[symbol] || '';
    area.disabled = !user;
    $('memoSave').disabled = !user;
    $('memoCount').textContent = `${area.value.length} / ${MEMO_LIMIT}`;
    $('memoStatus').textContent = user ? `${user.username}님 계정에만 저장됩니다. 비우고 저장하면 삭제됩니다.` : '로그인 후 종목별 메모를 저장할 수 있습니다.';
    renderMemoList();
  }
  function renderMemoList() {
    const list = $('memoList');
    const entries = Object.entries(memos);
    list.innerHTML = entries.length
      ? entries.map(([symbol, memo]) => `<tr data-symbol="${esc(symbol)}"><td class="txt">${esc(stockName(symbol))} <small>${esc(symbol)}</small></td><td class="txt memo-preview">${esc(memo)}</td></tr>`).join('')
      : `<tr><td class="empty" colspan="2">${user ? '저장한 메모가 없습니다.' : '로그인하면 저장한 메모가 여기에 모입니다.'}</td></tr>`;
  }
  async function loadMemos() {
    try {
      const me = await (await fetch('/api/member/me', { credentials: 'include' })).json();
      if (!me.loggedIn) return;
      user = me;
      const res = await fetch('/api/member/hts-memos', { credentials: 'include' });
      if (!res.ok) return;
      (await res.json()).memos.forEach(row => { memos[row.symbol] = row.memo; });
    } catch (_) {
      // 메모는 보조 기능이라 실패해도 거래 화면은 그대로 둔다.
    } finally {
      syncMemo();
    }
  }
  async function saveMemo() {
    if (!user) { location.href = '/member/login.html'; return; }
    const symbol = currentSymbol();
    const button = $('memoSave');
    button.disabled = true;
    try {
      const res = await fetch(`/api/member/hts-memos/${encodeURIComponent(symbol)}`, {
        method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memo: $('memoText').value }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '메모 저장에 실패했습니다.');
      if (data.memo) memos[symbol] = data.memo; else delete memos[symbol];
      syncMemo();
      $('memoStatus').textContent = data.memo ? '저장했습니다.' : '메모를 삭제했습니다.';
    } catch (error) {
      $('memoStatus').textContent = error.message;
    } finally {
      button.disabled = !user;
    }
  }

  /* ── 연결 ─────────────────────────────────────────────────────────── */
  document.querySelectorAll('[data-broker]').forEach(b => b.addEventListener('click', () => refreshBroker(b.dataset.broker)));
  $('brokerClear')?.addEventListener('click', () => {
    $('brokerLog').innerHTML = '<p class="brk-empty">로그를 비웠습니다. 다음 조회를 기다립니다.</p>';
  });
  $('memoText')?.addEventListener('input', e => { $('memoCount').textContent = `${e.target.value.length} / ${MEMO_LIMIT}`; });
  $('memoSave')?.addEventListener('click', saveMemo);
  $('memoList')?.addEventListener('click', e => {
    const symbol = e.target.closest('tr[data-symbol]')?.dataset.symbol;
    if (symbol && typeof selectStock === 'function') selectStock(symbol);
  });
  document.addEventListener('stock:selected', () => {
    syncMemo();
    const symbol = currentSymbol();
    $('brokerStatus').textContent = `${stockName(symbol)}(${symbol}) — KIS 또는 KB 조회를 누르면 요청·응답 원본이 아래에 쌓입니다.`;
  });
  loadMemos();
})();
