// AI 리서치 화면. 서버가 채운 숫자만 표시하고, 각 숫자를 계산 영수증 조회 API로 연결한다.
const $ra = selector => document.querySelector(selector);
const STATUS_TEXT = {
  refused: 'AI가 이 요청을 거절했습니다.',
  truncated: '답변이 길이 제한에서 잘려 표시하지 않습니다. 질문을 좁혀 다시 시도하세요.',
  unreceipted: '영수증으로 확인되지 않는 숫자가 들어 있어 답변을 표시하지 않습니다.',
  turn_limit: '도구 호출 횟수 제한에 도달했습니다. 질문을 좁혀 다시 시도하세요.',
};

function renderAnswer(answer) {
  const byId = Object.fromEntries(answer.numbers.map(n => [n.id, n]));
  // 먼저 전체를 이스케이프하고, 그다음 자리표시자만 서버가 준 값으로 바꾼다.
  const html = escapeHtml(answer.template).replace(/\{\{\s*(n\d{1,3})\s*\}\}/g, (match, id) => {
    const n = byId[id];
    if (!n) return escapeHtml(match);
    const href = `/api/quant/backtests/${encodeURIComponent(n.receiptId)}`;
    return `<a class="ra-num" href="${href}" target="_blank" rel="noopener" title="${escapeHtml(`${n.path} · 영수증 ${n.receiptId.slice(0, 12)}`)}">${escapeHtml(n.display)}</a>`;
  });
  $ra('[data-answer]').innerHTML = html;
  $ra('[data-receipts]').innerHTML = answer.receipts.length
    ? '근거 영수증: ' + answer.receipts.map(id => `<a href="/api/quant/backtests/${encodeURIComponent(id)}" target="_blank" rel="noopener"><code>${escapeHtml(id.slice(0, 12))}</code></a>`).join(' · ')
    : '숫자 없이 답했습니다.';
}

async function loadStatus() {
  const box = $ra('[data-status]');
  try {
    const response = await fetch('/api/agent/status', { credentials: 'same-origin' });
    if (response.status === 404) { box.textContent = '이 배포에는 AI 리서치 기능이 없습니다.'; return; }
    const data = await response.json();
    if (!data.enabled) { box.textContent = 'AI 리서치가 꺼져 있습니다. 운영자가 예산을 정하고 켜야 쓸 수 있습니다.'; return; }
    const me = await fetch('/api/member/me', { credentials: 'same-origin' });
    if (!me.ok) { box.innerHTML = '로그인이 필요합니다. <a href="/member/login.html">로그인</a>'; return; }
    $ra('[data-redeem]').hidden = false;
    if (data.invite && data.invite.usable) {
      box.textContent = `초대 코드 "${data.invite.label}" · 남은 질문 ${data.invite.requestsLeft}회 · 만료 ${data.invite.expiresAt.slice(0, 10)} · 모델 ${data.model}`;
      $ra('[data-ask]').hidden = false;
    } else {
      box.textContent = data.invite ? '등록된 초대 코드를 더 쓸 수 없습니다. 새 코드를 등록하세요.' : '초대 코드를 등록하면 질문할 수 있습니다.';
    }
  } catch (error) { box.innerHTML = `<span class="ra-error">${escapeHtml(error.message)}</span>`; }
}

async function redeem() {
  const status = $ra('[data-redeem-status]');
  const response = await fetch('/api/agent/redeem', {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: $ra('[data-code]').value.trim() }),
  });
  const data = await response.json().catch(() => ({}));
  status.innerHTML = response.ok ? escapeHtml(data.message) : `<span class="ra-error">${escapeHtml(data.message || '등록 실패')}</span>`;
  if (response.ok) loadStatus();
}

async function ask() {
  const button = $ra('[data-ask-btn]'), status = $ra('[data-ask-status]');
  const question = $ra('[data-question]').value.trim();
  if (!question) return;
  button.disabled = true; status.textContent = 'AI가 백테스트를 실행하고 답을 정리하는 중… (수십 초 걸릴 수 있습니다)';
  $ra('[data-result]').hidden = true;
  try {
    const response = await fetch('/api/agent/ask', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || '요청 실패');
    const cost = `도구 호출 ${data.toolCalls.length}회 · 토큰 ${Object.values(data.usage).reduce((a, b) => a + b, 0).toLocaleString()} · 약 $${data.costUsd.toFixed(4)}`;
    if (data.answer && (data.status === 'answered' || data.status === 'out_of_scope')) {
      renderAnswer(data.answer);
      $ra('[data-result]').hidden = false;
      status.textContent = cost;
    } else {
      status.innerHTML = `<span class="ra-error">${escapeHtml(STATUS_TEXT[data.status] || data.status)}</span> · ${escapeHtml(cost)}`;
    }
  } catch (error) {
    status.innerHTML = `<span class="ra-error">${escapeHtml(error.message)}</span>`;
  } finally { button.disabled = false; loadStatus(); }
}

document.addEventListener('DOMContentLoaded', async () => {
  await initPage();
  $ra('[data-redeem-btn]').addEventListener('click', redeem);
  $ra('[data-ask-btn]').addEventListener('click', ask);
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => { $ra('[data-question]').value = button.textContent; }));
  loadStatus();
});
