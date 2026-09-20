// KIS Testbed 읽기 전용 연결 테스트 화면(/broker-api-test.html) 전용 스크립트.
// KB증권 테스트는 /kb-api-test.html + /js/kb-api-test.js 로 분리되어 있다.
(() => {
  const apiBase = window.APP_CONFIG?.apiBase || '';
  const SYMBOL_RE = /^\d{6}$/;

  const num = (v, unit = '') => {
    if (v === null || v === undefined || v === '') return '-';
    const n = Number(String(v).replace(/,/g, ''));
    return Number.isFinite(n) ? `${n.toLocaleString()}${unit}` : `${v}${unit}`;
  };
  const pad = (s, w) => String(s).padStart(w, ' ');
  const symbol = () => {
    const value = document.getElementById('kis-symbol').value.trim();
    if (!SYMBOL_RE.test(value)) throw new Error('종목코드는 6자리 숫자로 입력하세요. (예: 005930)');
    return value;
  };

  // ── 응답 포맷터: 서버가 정규화한 KIS 필드만 사람이 읽기 쉬운 줄로 바꾼다.
  const formatters = {
    quote(data) {
      const q = data.quote;
      return [
        '성공 · 현재가', `증권사: ${q.broker}`, `종목코드: ${q.symbol}`,
        `현재가: ${num(q.price, '원')}`, `전일대비: ${num(q.change, '원')}`,
        `등락률: ${q.changeRate ?? '-'}%`, `누적거래량: ${num(q.volume, '주')}`,
        `체결시각: ${q.tradeTime || '-'}`,
      ].join('\n');
    },
    chart(data) {
      const c = data.chart;
      const rows = (c.candles || []).slice(0, 10);
      const head = `${pad('일자', 8)}  ${pad('시가', 9)} ${pad('고가', 9)} ${pad('저가', 9)} ${pad('종가', 9)} ${pad('거래량', 12)}`;
      const body = rows.map((r) => `${pad(r.date, 8)}  ${pad(num(r.open), 9)} ${pad(num(r.high), 9)} ${pad(num(r.low), 9)} ${pad(num(r.close), 9)} ${pad(num(r.volume), 12)}`);
      return [`성공 · 일봉 ${c.candles?.length ?? 0}건 (최근 ${rows.length}건 표시)`, `종목코드: ${c.symbol}`, '', head, ...body].join('\n');
    },
    orderbook(data) {
      const o = data.orderbook;
      const levels = (o.levels || []).slice(0, 10);
      const head = `${pad('단계', 4)}  ${pad('매도잔량', 10)} ${pad('매도호가', 10)} | ${pad('매수호가', 10)} ${pad('매수잔량', 10)}`;
      const body = levels.map((l) => `${pad(l.level, 4)}  ${pad(num(l.askQty), 10)} ${pad(num(l.askPrice), 10)} | ${pad(num(l.bidPrice), 10)} ${pad(num(l.bidQty), 10)}`);
      return [
        `성공 · 호가 ${levels.length}단계`, `종목코드: ${o.symbol}`,
        `총 매도잔량: ${num(o.totalAskQty, '주')} · 총 매수잔량: ${num(o.totalBidQty, '주')}`, '', head, ...body,
      ].join('\n');
    },
    balance(data) {
      const b = data.balance;
      const lines = [
        '성공 · 모의계좌 잔고', `증권사: ${b.broker}`,
        `예수금: ${num(b.cashBalance, '원')}`, `총 평가금액: ${num(b.totalEvalAmount, '원')}`,
        `평가손익 합계: ${num(b.totalProfitLoss, '원')}`, `보유 종목 수: ${b.holdingsCount ?? 0}`,
      ];
      (b.holdings || []).forEach((h) => {
        lines.push(`  - ${h.name || h.symbol} (${h.symbol}): ${num(h.quantity, '주')} · 평균단가 ${num(h.avgPrice, '원')} · 평가 ${num(h.evalAmount, '원')} · 손익 ${num(h.profitLoss, '원')} (${h.profitLossRate ?? '-'}%)`);
      });
      if (!b.holdings?.length) lines.push('  (보유 종목 없음)');
      return lines.join('\n');
    },
    index(data) {
      const i = data.index;
      return [
        `성공 · ${i.index} 지수`, `증권사: ${i.broker}`, `현재 지수: ${num(i.price)}`,
        `전일대비: ${num(i.change)}`, `등락률: ${i.changeRate ?? '-'}%`, `누적거래량: ${num(i.volume)}`,
      ].join('\n');
    },
  };

  // ── 각 테스트: 요청 경로와 결과 표시 대상
  const tests = {
    'kis-quote': { path: () => `/api/broker-test/kis/quote?symbol=${symbol()}`, format: formatters.quote, result: 'kis-result' },
    'kis-chart': { path: () => `/api/broker-test/kis/chart?symbol=${symbol()}`, format: formatters.chart, result: 'kis-chart-result' },
    'kis-orderbook': { path: () => `/api/broker-test/kis/orderbook?symbol=${symbol()}`, format: formatters.orderbook, result: 'kis-orderbook-result' },
    'kis-balance': { path: () => '/api/broker-test/kis/balance', format: formatters.balance, result: 'kis-balance-result' },
    'kis-index': {
      path: () => `/api/broker-test/kis/index?code=${encodeURIComponent(document.getElementById('kis-index-code').value)}`,
      format: formatters.index, result: 'kis-index-result',
    },
  };

  async function parseJson(response) {
    const text = await response.text();
    try { return JSON.parse(text); } catch { throw new Error(`서버 응답을 해석할 수 없습니다 (HTTP ${response.status}). 백엔드 상태를 확인하세요.`); }
  }

  const render = (result, text, raw, isError) => {
    result.textContent = text;
    result.classList.toggle('result--error', isError);
    if (raw !== undefined) {
      const details = document.createElement('details');
      details.style.marginTop = '8px';
      const summary = document.createElement('summary');
      summary.textContent = '원본 응답(JSON) 보기';
      summary.style.cursor = 'pointer';
      const pre = document.createElement('pre');
      pre.style.margin = '6px 0 0';
      pre.style.whiteSpace = 'pre-wrap';
      pre.textContent = JSON.stringify(raw, null, 2);
      details.append(summary, pre);
      result.append('\n', details);
    }
  };

  const runTest = async (button) => {
    const test = tests[button.dataset.test];
    const result = document.getElementById(test.result);
    let path;
    try { path = test.path(); } catch (error) { render(result, error.message, undefined, true); return; }
    button.disabled = true;
    render(result, '서버에서 KIS Testbed 읽기 전용 API를 호출하는 중…', undefined, false);
    try {
      const response = await fetch(`${apiBase}${path}`);
      const data = await parseJson(response);
      if (!data.ok) { render(result, `점검 결과: 실패\n${data.message || '알 수 없는 오류'}`, data, true); return; }
      render(result, test.format(data), data, false);
    } catch (error) {
      render(result, `요청 실패\n${error.message}`, undefined, true);
    } finally { button.disabled = false; }
  };

  document.querySelectorAll('[data-test]').forEach((button) => {
    button.addEventListener('click', () => runTest(button));
  });
  document.getElementById('kis-symbol')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') document.querySelector('[data-test="kis-quote"]')?.click();
  });
})();
