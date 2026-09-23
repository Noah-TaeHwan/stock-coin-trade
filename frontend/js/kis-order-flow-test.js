(() => {
  const apiBase = window.APP_CONFIG?.apiBase || '';
  const confirm = document.getElementById('confirm');
  const run = document.getElementById('run');
  const result = document.getElementById('result');
  let loggedIn = false;
  let canUseKisAccount = false;
  let csrfToken = '';

  const won = (v) => `${Number(v).toLocaleString()}원`;

  // 헤더를 그리는 initPage()가 로그인 사용자를 돌려주므로, 그 값으로 실행 버튼을 잠근다.
  document.addEventListener('DOMContentLoaded', async () => {
    const user = await initPage();
    loggedIn = !!user?.loggedIn;
    canUseKisAccount = !!user?.canUseKisAccount;
    csrfToken = user?.csrfToken || '';
    if (!loggedIn || !canUseKisAccount) {
      confirm.disabled = true;
      run.disabled = true;
      result.innerHTML = !loggedIn
        ? '로그인 후 실행할 수 있습니다. <a href="/member/login.html" style="color:#93C5FD;text-decoration:underline">로그인 페이지로 이동 →</a>'
        : '로그인한 회원만 실행할 수 있습니다.';
    }
  });

  confirm.addEventListener('change', () => { run.disabled = !(loggedIn && canUseKisAccount && confirm.checked); });

  async function parseJson(response) {
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch {
      // nginx 502/504 같은 HTML 응답은 그대로 보여 주지 않고 상태 코드만 전달한다.
      throw new Error(`서버 응답을 해석할 수 없습니다 (HTTP ${response.status}). 백엔드 상태를 확인하세요.`);
    }
  }

  run.addEventListener('click', async () => {
    run.disabled = true;
    confirm.disabled = true;
    result.classList.remove('error');
    result.textContent = 'KIS Testbed에서 모의 주문 → 정정 → 취소를 실행하는 중… (최대 1분)';
    try {
      const approvalResponse = await fetch(`${apiBase}/api/broker-test/kis/order-flow-approval`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      });
      const approval = await parseJson(approvalResponse);
      if (!approvalResponse.ok || !approval.ok) throw new Error(approval.message || '주문 실행 승인을 받지 못했습니다.');
      const response = await fetch(`${apiBase}/api/broker-test/kis/order-flow-test`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ approvalToken: approval.approvalToken }),
      });
      const data = await parseJson(response);
      if (response.status === 401) loggedIn = false;
      if (!response.ok || !data.ok) throw new Error(data.message || '테스트를 완료하지 못했습니다.');
      const test = data.test;
      const amendLine = test.amend === 'success'
        ? `정정: 성공 (${won(test.amendedPrice)})`
        : `정정: 실패 — ${test.amendMessage || '사유 미상'} (원주문을 취소했습니다)`;
      const cancelLine = test.cancel === 'success'
        ? `취소: 성공${test.cancelMessage ? ` — ${test.cancelMessage}` : ''}`
        : `취소: 실패 — ${test.cancelMessage || '사유 미상'}`;
      result.textContent = [
        test.amend === 'success' ? '테스트 성공' : '테스트 완료 (정정 단계 실패, 주문은 정리됨)',
        `환경: ${test.environment}`, `종목: ${test.symbol}`,
        `안전 확인 현재가: ${won(test.currentPrice)}`,
        `주문: 성공 (${won(test.testPrice)} 지정가 1주, 현재가의 90%)`,
        amendLine, cancelLine,
      ].join('\n');
      if (test.amend !== 'success') result.classList.add('error');
    } catch (error) {
      result.textContent = `테스트 실패\n${error.message}`;
      result.classList.add('error');
    } finally {
      confirm.disabled = !(loggedIn && canUseKisAccount);
      run.disabled = !(loggedIn && canUseKisAccount && confirm.checked);
    }
  });
})();
