// KB증권 Open API 읽기 전용 테스트 화면(/kb-api-test.html) 전용 스크립트.
// (이전에는 broker-api-test.js 를 KIS 화면과 공유했으나, KIS 화면이 KIS 전용이 되면서 분리했다.)
(() => {
  const apiBase = window.APP_CONFIG?.apiBase || '';
  const SYMBOL_RE = /^\d{6}$/;

  const formatTokenCheck = (data) => {
    if (!data.ok) return `점검 결과: 실패\n${data.message || '알 수 없는 오류'}`;
    const c = data.check;
    return ['성공', `증권사: ${c.broker}`, `토큰 유형: ${c.tokenType}`, `유효기간: ${c.expiresIn}초`].join('\n');
  };

  const kbSymbolPath = (path) => {
    const symbol = document.getElementById('kb-symbol').value.trim();
    if (!SYMBOL_RE.test(symbol)) throw new Error('종목코드는 6자리 숫자로 입력하세요.');
    return `/api/broker-test/kb${path}?symbol=${encodeURIComponent(symbol)}`;
  };

  const testBuilders = {
    'kb-quote': () => kbSymbolPath('/quote'),
    'kb-base-info': () => kbSymbolPath('/base-info'),
    'kb-orderbook': () => kbSymbolPath('/orderbook'),
    'kb-chart': () => kbSymbolPath('/chart'),
  };

  async function parseJson(response) {
    const text = await response.text();
    try { return JSON.parse(text); } catch { throw new Error(`서버 응답을 해석할 수 없습니다 (HTTP ${response.status}). 백엔드 상태를 확인하세요.`); }
  }

  const runTokenCheck = async (button) => {
    const result = document.getElementById('kb-result');
    button.disabled = true;
    result.classList.remove('result--error');
    result.textContent = '서버에서 KB 토큰 발급을 점검하는 중…';
    try {
      const data = await parseJson(await fetch(`${apiBase}/api/broker-test/kb/token`));
      result.textContent = formatTokenCheck(data);
      result.classList.toggle('result--error', !data.ok);
    } catch (error) {
      result.textContent = `요청 실패\n${error.message}`;
      result.classList.add('result--error');
    } finally { button.disabled = false; }
  };

  // KB 조회 응답은 TR마다 형태가 달라 원본 JSON을 그대로 보여 준다.
  const runGenericTest = async (button) => {
    const testId = button.dataset.test;
    const result = document.getElementById(`${testId}-result`);
    let path;
    try { path = testBuilders[testId](); } catch (error) { result.textContent = error.message; return; }
    button.disabled = true;
    result.classList.remove('result--error');
    result.textContent = '서버에서 읽기 전용 API를 호출하는 중…';
    try {
      const data = await parseJson(await fetch(`${apiBase}${path}`));
      result.textContent = JSON.stringify(data, null, 2);
      result.classList.toggle('result--error', !data.ok);
    } catch (error) {
      result.textContent = `요청 실패\n${error.message}`;
      result.classList.add('result--error');
    } finally { button.disabled = false; }
  };

  document.querySelectorAll('.run[data-broker="kb"]').forEach((button) => {
    button.addEventListener('click', () => runTokenCheck(button));
  });
  document.querySelectorAll('.run-sm[data-test^="kb-"]').forEach((button) => {
    button.addEventListener('click', () => runGenericTest(button));
  });
})();
