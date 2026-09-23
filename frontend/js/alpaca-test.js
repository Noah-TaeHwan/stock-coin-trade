(async () => {
  const user = await initPage({ requireAuth: true });
  if (!user) return;
  const apiBase = window.APP_CONFIG?.apiBase || '';
  try {
    const statusResponse = await apiFetch('/api/alpaca-test/status');
    const statusData = await statusResponse.json();
    const status = statusData.status || {};
    const config = document.getElementById('alpacaConfig');
    const mode = document.getElementById('alpacaMode');
    if (config) {
      config.className = `alpaca-status ${status.configured ? 'ok' : 'bad'}`;
      config.textContent = `${status.configured ? '✓' : '!'} ${status.configured ? `설정 준비 · ${status.source}` : 'Key·Secret 필요'}`;
    }
    if (mode) {
      const paperOnly = status.mode === 'paper' && !status.liveEnabled;
      mode.className = `alpaca-status ${paperOnly ? 'ok' : 'bad'}`;
      mode.textContent = `${paperOnly ? '✓' : '!'} ${paperOnly ? 'Paper API 고정' : '환경 확인 필요'}`;
    }
  } catch (error) {
    const config = document.getElementById('alpacaConfig');
    if (config) { config.className = 'alpaca-status bad'; config.textContent = '! 설정 확인 실패'; }
  }
  const button = document.getElementById('run-test');
  const result = document.getElementById('result');
  if (button && result) {
    button.addEventListener('click', async () => {
      button.disabled = true;
      result.classList.remove('result--error');
      result.textContent = 'Alpaca Paper API에 읽기 전용 요청을 보내는 중…';
      try {
        const response = await fetch(`${apiBase}/api/alpaca-test/paper/account`);
        const data = await response.json();
        if (!data.ok) {
          result.classList.add('result--error');
          result.textContent = `점검 결과: 실패\n${data.message || '알 수 없는 오류'}`;
          return;
        }
        const info = data.result;
        result.textContent = [
          '점검 결과: 성공', `환경: ${info.environment}`, `연결: ${info.connection}`,
          `계정 상태: ${info.accountStatus || '-'}`, `통화: ${info.currency || '-'}`,
          `거래 차단: ${info.tradingBlocked ? '예' : '아니오'}`,
          `계정 차단: ${info.accountBlocked ? '예' : '아니오'}`,
        ].join('\n');
      } catch (error) {
        result.classList.add('result--error');
        result.textContent = `요청 실패\n${error.message}`;
      } finally { button.disabled = false; }
    });
  }

  const testBuilders = {
    positions: () => '/api/alpaca-test/paper/positions',
    orders: () => '/api/alpaca-test/paper/orders',
    clock: () => '/api/alpaca-test/market/clock',
    quote: () => {
      const symbol = document.getElementById('quote-symbol').value.trim();
      if (!/^[A-Za-z]{1,5}$/.test(symbol)) throw new Error('티커는 1~5자리 영문으로 입력하세요.');
      return `/api/alpaca-test/market/quote?symbol=${encodeURIComponent(symbol)}`;
    },
  };

  document.querySelectorAll('.run-sm[data-test]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const testId = btn.dataset.test;
      const box = document.getElementById(`${testId}-result`);
      let path;
      try {
        path = testBuilders[testId]();
      } catch (error) {
        box.textContent = error.message;
        return;
      }
      btn.disabled = true;
      box.classList.remove('result--error');
      box.textContent = '서버에서 읽기 전용 API를 호출하는 중…';
      try {
        const response = await fetch(`${apiBase}${path}`);
        const data = await response.json();
        box.textContent = JSON.stringify(data, null, 2);
        box.classList.toggle('result--error', !data.ok);
      } catch (error) {
        box.textContent = `요청 실패\n${error.message}`;
        box.classList.add('result--error');
      } finally { btn.disabled = false; }
    });
  });
})();
