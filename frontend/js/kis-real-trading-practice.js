(() => {
  const base = window.APP_CONFIG?.apiBase || '';
  let user = null;
  let side = 'BUY';
  let quote = null;

  const el = id => document.getElementById(id);
  const won = value => `${Number(value || 0).toLocaleString('ko-KR')}원`;

  async function jsonFetch(path, options = {}) {
    const response = await fetch(base + path, { credentials: 'include', ...options });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { message: `서버 응답을 해석할 수 없습니다 (HTTP ${response.status}).` }; }
    if (!response.ok) {
      const error = new Error(data.message || '요청을 처리하지 못했습니다.');
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function selectedSymbol() { return el('stockSelect').value; }

  function setSetupState(id, ready, label) {
    const item = el(id);
    item.classList.toggle('ready', ready);
    item.textContent = `${ready ? '✓' : '○'} ${label}`;
  }

  async function loadRealStatus() {
    const status = await jsonFetch('/api/kis-real/status');
    setSetupState('realAppKeyState', status.configured.appKey, '실전 App Key');
    setSetupState('realSecretState', status.configured.appSecret, '실전 App Secret');
    setSetupState('realAccountState', status.configured.account && status.accountFormatValid, '실전 계좌번호');
    setSetupState('realOwnerState', status.configured.ownerEmail, '계좌 소유자');
    el('realBalanceBtn').disabled = !(status.ready && status.authorized);
    if (status.ready && status.authorized) {
      el('realStatus').className = 'message show success';
      el('realStatus').innerHTML = '<strong>실전 잔고조회 준비 완료</strong><br>조회 버튼은 읽기 전용 TTTC8434R만 호출하며 주문 API는 호출하지 않습니다.';
    } else if (status.ready) {
      el('realStatus').className = 'message show error';
      el('realStatus').innerHTML = `<strong>조회 권한 없음</strong><br>${escapeHtml(status.message)}`;
    }
  }

  async function loadRealBalance() {
    const button = el('realBalanceBtn');
    button.disabled = true;
    button.textContent = '실전 잔고 조회 중…';
    try {
      const data = await jsonFetch('/api/kis-real/balance', {
        method: 'POST', headers: { 'Content-Type':'application/json', 'X-CSRF-Token': user.csrfToken || '' }, body: '{}',
      });
      const balance = data.balance;
      el('realCash').textContent = won(balance.cashBalance);
      el('realTotal').textContent = won(balance.totalEvalAmount);
      el('realPnl').textContent = won(balance.totalProfitLoss);
      el('realSummary').classList.add('show');
      el('realHoldingsWrap').style.display = 'block';
      el('realHoldingsBody').innerHTML = balance.holdings?.length ? balance.holdings.map(position => `<tr><td>${escapeHtml(position.name)}<br><small>${escapeHtml(position.symbol)}</small></td><td>${Number(position.quantity || 0).toLocaleString()}주</td><td>${won(position.avgPrice)}</td><td>${won(position.currentPrice)}</td><td>${won(position.evalAmount)}</td><td>${won(position.profitLoss)}</td></tr>`).join('') : '<tr><td colspan="6" class="empty">실전 보유종목이 없습니다.</td></tr>';
      el('realStatus').className = 'message show success';
      el('realStatus').innerHTML = '<strong>KIS 실전 잔고조회 성공</strong><br>읽기 전용 조회이며 주문이나 계좌 변경은 발생하지 않았습니다.';
    } catch (error) {
      el('realStatus').className = 'message show error';
      el('realStatus').innerHTML = `<strong>실전 잔고조회 실패</strong><br>${escapeHtml(error.message)}`;
    } finally {
      button.disabled = false;
      button.textContent = '실전 잔고조회';
    }
  }

  async function loadStocks(query = '') {
    const path = query ? `/api/stocks/search?q=${encodeURIComponent(query)}&limit=30` : '/api/stocks/list?limit=50';
    const data = await jsonFetch(path);
    const stocks = data.stocks || [];
    const select = el('stockSelect');
    const previous = selectedSymbol();
    const merged = stocks.some(stock => stock.symbol === '005930') ? stocks : [{ symbol:'005930', name:'삼성전자', market:'KOSPI' }, ...stocks];
    select.innerHTML = merged.map(stock => `<option value="${escapeHtml(stock.symbol)}">${escapeHtml(stock.name)} (${escapeHtml(stock.symbol)})</option>`).join('');
    if (merged.some(stock => stock.symbol === previous)) select.value = previous;
    await loadQuote();
  }

  async function loadQuote() {
    quote = await jsonFetch(`/api/stocks/quote?symbol=${encodeURIComponent(selectedSymbol())}`);
    el('quoteName').textContent = quote.name || selectedSymbol();
    el('quoteSymbol').textContent = quote.symbol || selectedSymbol();
    el('quotePrice').textContent = won(quote.price);
    const rate = Number(quote.changeRate || 0);
    el('quoteChange').textContent = `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%`;
    el('quoteChange').style.color = rate > 0 ? 'var(--up)' : rate < 0 ? 'var(--down)' : 'var(--muted)';
    updateEstimate();
  }

  function updateEstimate() {
    const quantity = Math.max(0, Math.floor(Number(el('quantity').value) || 0));
    el('estimatedAmount').textContent = quote?.price && quantity ? won(quote.price * quantity) : '-';
  }

  function setMessage(message, type = 'error', detail = '') {
    const box = el('orderMessage');
    box.className = `message show ${type}`;
    box.innerHTML = `<strong>${escapeHtml(message)}</strong>${detail ? `<br>${escapeHtml(detail)}` : ''}`;
  }

  async function refreshAccount() {
    const [account, positions, history] = await Promise.all([
      jsonFetch('/api/kis-practice/account'), jsonFetch('/api/kis-practice/positions'), jsonFetch('/api/kis-practice/orders/history?limit=20'),
    ]);
    el('cash').textContent = won(account.cash);
    el('totalAsset').textContent = won(account.totalAsset);
    const rate = Number(account.totalPnlRate || 0);
    el('pnlRate').textContent = `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%`;
    el('pnlRate').style.color = rate > 0 ? 'var(--up)' : rate < 0 ? 'var(--down)' : 'var(--fg)';
    el('positionsBody').innerHTML = positions.positions?.length ? positions.positions.map(position => `<tr><td>${escapeHtml(position.name)}<br><small>${escapeHtml(position.symbol)}</small></td><td>${Number(position.quantity).toLocaleString()}주</td><td>${won(position.avgPrice)}</td><td>${won(position.evalAmount)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">보유종목이 없습니다.</td></tr>';
    const practiceHistory = history.history || [];
    el('historyBody').innerHTML = practiceHistory.length ? practiceHistory.map(order => `<tr><td>${escapeHtml(order.name)}<br><small>${escapeHtml(order.symbol)}</small></td><td style="color:${order.type === 'BUY' ? 'var(--up)' : 'var(--down)'};font-weight:800">${order.type === 'BUY' ? '매수' : '매도'}</td><td>${Number(order.quantity).toLocaleString()}주</td><td>${won(order.price)}</td><td>${won(order.amount)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">이 화면에서 체결한 내역이 없습니다.</td></tr>';
  }

  async function submitOrder() {
    const quantity = Number(el('quantity').value);
    if (!Number.isInteger(quantity) || quantity < 1) { setMessage('주문수량은 1주 이상의 정수여야 합니다.'); return; }
    const button = el('orderBtn');
    button.disabled = true;
    el('orderMessage').className = 'message';
    try {
      const result = await jsonFetch('/api/kis-practice/orders', {
        method: 'POST',
        headers: { 'Content-Type':'application/json', 'X-CSRF-Token': user.csrfToken || '' },
        body: JSON.stringify({ symbol: selectedSymbol(), side, quantity }),
      });
      setMessage(`${side === 'BUY' ? '매수' : '매도'} 연습 주문이 체결되었습니다.`, 'success', `${result.quantity}주 · ${won(result.price)} · 총 ${won(result.amount)}`);
      await Promise.all([refreshAccount(), loadQuote()]);
    } catch (error) {
      if (error.data?.error === 'INSUFFICIENT_BALANCE') {
        setMessage('잔고 부족으로 매수할 수 없습니다.', 'balance', `필요 ${won(error.data.requiredAmount)} · 예수금 ${won(error.data.availableCash)} · 부족 ${won(error.data.shortageAmount)}`);
      } else if (error.data?.error === 'INSUFFICIENT_POSITION') {
        setMessage('보유수량 부족으로 매도할 수 없습니다.', 'error', `주문 ${error.data.requestedQuantity || quantity}주 · 매도 가능 ${error.data.availableQuantity || 0}주`);
      } else setMessage(error.message);
    } finally { button.disabled = false; }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    user = await initPage({ requireAuth: true });
    if (!user) return;
    document.querySelectorAll('.side-btn[data-side]').forEach(button => button.addEventListener('click', () => {
      side = button.dataset.side;
      document.querySelectorAll('.side-btn[data-side]').forEach(item => item.classList.toggle('active', item === button));
      el('orderBtn').textContent = `${side === 'BUY' ? '매수' : '매도'} 주문`;
      el('orderBtn').classList.toggle('sell', side === 'SELL');
    }));
    el('stockSelect').addEventListener('change', () => loadQuote().catch(error => setMessage(error.message)));
    el('quantity').addEventListener('input', updateEstimate);
    el('orderBtn').addEventListener('click', submitOrder);
    el('realBalanceBtn').addEventListener('click', loadRealBalance);
    el('searchBtn').addEventListener('click', () => loadStocks(el('symbolSearch').value.trim()).catch(error => setMessage(error.message)));
    el('symbolSearch').addEventListener('keydown', event => { if (event.key === 'Enter') el('searchBtn').click(); });
    try { await Promise.all([loadRealStatus(), loadStocks(), refreshAccount()]); } catch (error) { setMessage(error.message); }
  });
})();
