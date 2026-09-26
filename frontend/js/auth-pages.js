'use strict';
// 인증 화면 공용 스크립트. 외부·인라인 스크립트 없이 CSP 'self'로 동작한다. 사용자 입력은 textContent로만 출력한다.
const AUTH_API = window.APP_CONFIG?.apiBase ?? '';

/**
 * JSON POST를 보내고 상태와 본문을 돌려준다.
 * @param {string} path API 경로
 * @param {object} body 요청 본문
 * @returns {Promise<{status: number, data: object}>} 상태 코드와 JSON 본문(없으면 {})
 */
async function postJson(path, body) {
  const res = await fetch(AUTH_API + path, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
  return { status: res.status, data };
}

/**
 * 현재 로그인 상태를 가져온다.
 * @returns {Promise<object>} /api/member/me 응답(실패하면 {})
 */
async function currentMember() {
  try {
    const res = await fetch(AUTH_API + '/api/member/me', { credentials: 'include' });
    return await res.json();
  } catch (_) { return {}; }
}

/**
 * 안내 문구를 보여 준다.
 * @param {string} text 문구
 * @param {'error'|'ok'} kind 종류(색)
 * @returns {void}
 */
function say(text, kind = 'error') {
  const el = document.getElementById('message');
  el.textContent = text;
  el.dataset.kind = kind;
  el.hidden = false;
}

/**
 * 입력 값을 읽는다.
 * @param {string} id 요소 id
 * @returns {string} 값
 */
const valueOf = id => document.getElementById(id).value;

/**
 * 체크 상자 상태를 읽는다.
 * @param {string} id 요소 id
 * @returns {boolean} 체크 여부
 */
const isChecked = id => document.getElementById(id).checked;

/**
 * 서버 오류 본문에서 보여 줄 문구를 고른다.
 * @param {number} status HTTP 상태
 * @param {object} data 응답 본문
 * @param {string} fallback 기본 문구
 * @returns {string} 문구
 */
function errorText(status, data, fallback) {
  if (status === 429) return '시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.';
  return data.message || data.error || fallback;
}

/**
 * 폼 제출을 가로채 handler를 실행하고, 실행 중에는 제출 버튼을 잠근다.
 * @param {string} formId 폼 id
 * @param {() => Promise<void>} handler 제출 처리
 * @returns {void}
 */
function onSubmit(formId, handler) {
  const form = document.getElementById(formId);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    document.getElementById('message').hidden = true;
    try { await handler(); } catch (_) { say('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.'); }
    finally { button.disabled = false; }
  });
}

const PAGES = {
  login() {
    onSubmit('form', async () => {
      const { status, data } = await postJson('/api/member/login', { email: valueOf('email'), password: valueOf('password') });
      if (status === 200) { location.href = '/trade/order.html'; return; }
      say(errorText(status, data, '로그인에 실패했습니다.'));
    });
  },

  async register() {
    const me = await currentMember();
    if (me.signupOpen === false) {
      say('공개 베타 준비 중이라 지금은 가입을 받지 않습니다.');
      document.getElementById('submit').disabled = true;
      return;
    }
    onSubmit('form', async () => {
      const { status, data } = await postJson('/api/member/register', {
        username: valueOf('username'), email: valueOf('email'), password: valueOf('password'),
        password2: valueOf('password2'), agreeAge: isChecked('agreeAge'), agreePrivacy: isChecked('agreePrivacy'),
        website: valueOf('website'),
      });
      if (status === 202) {
        document.getElementById('form').hidden = true;
        say('확인 메일을 보냈습니다. 메일의 링크를 열면 가입이 끝납니다. 메일이 없으면 스팸함을 확인해 주세요.', 'ok');
        return;
      }
      if (status === 200) { location.href = '/trade/order.html'; return; }
      say(errorText(status, data, '가입에 실패했습니다.'));
    });
  },

  async verify() {
    const resend = document.getElementById('resend');
    onSubmit('resend', async () => {
      await postJson('/api/member/verify/resend', { email: valueOf('email') });
      say('가입했지만 아직 인증하지 않은 주소라면 인증 메일을 다시 보냈습니다.', 'ok');
    });
    if (!window.__authToken) { resend.hidden = false; return; }
    const { status, data } = await postJson('/api/member/verify', { token: window.__authToken });
    if (status === 200) {
      say('이메일 인증이 끝났습니다. 이제 로그인할 수 있습니다.', 'ok');
      document.getElementById('toLogin').hidden = false;
      return;
    }
    say(errorText(status, data, '인증하지 못했습니다.'));
    resend.hidden = false;
  },

  'reset-request'() {
    onSubmit('form', async () => {
      await postJson('/api/member/password/reset-request', { email: valueOf('email') });
      document.getElementById('form').hidden = true;
      say('가입된 주소라면 재설정 메일을 보냈습니다. 링크는 30분 동안 쓸 수 있습니다.', 'ok');
    });
  },

  reset() {
    if (!window.__authToken) {
      document.getElementById('form').hidden = true;
      say('재설정 링크가 없습니다. 비밀번호 찾기에서 메일을 다시 받아 주세요.');
      return;
    }
    onSubmit('form', async () => {
      const { status, data } = await postJson('/api/member/password/reset', {
        token: window.__authToken, password: valueOf('password'), password2: valueOf('password2'),
      });
      if (status === 200) {
        document.getElementById('form').hidden = true;
        say('비밀번호를 바꿨습니다. 모든 기기에서 로그아웃되었으니 새 비밀번호로 로그인해 주세요.', 'ok');
        document.getElementById('toLogin').hidden = false;
        return;
      }
      say(errorText(status, data, '비밀번호를 바꾸지 못했습니다.'));
    });
  },

  async account() {
    const me = await currentMember();
    if (!me.loggedIn) { location.href = '/member/login.html'; return; }
    document.getElementById('who').textContent = me.username || '';
    onSubmit('change', async () => {
      const { status, data } = await postJson('/api/member/password/change', {
        current: valueOf('current'), password: valueOf('password'), password2: valueOf('password2'),
      });
      if (status === 200) {
        document.getElementById('change').reset();
        say('비밀번호를 바꿨습니다. 다른 기기는 로그아웃되었습니다.', 'ok');
        return;
      }
      say(errorText(status, data, '비밀번호를 바꾸지 못했습니다.'));
    });
    onSubmit('everywhere', async () => {
      await postJson('/api/member/logout-all', {});
      location.href = '/member/login.html';
    });
    onSubmit('remove', async () => {
      if (!isChecked('confirmDelete')) { say('탈퇴하면 모든 기록이 즉시 지워집니다. 확인란을 체크해 주세요.'); return; }
      const { status, data } = await postJson('/api/member/delete', { password: valueOf('deletePassword') });
      if (status === 200) { location.href = '/index.html'; return; }
      say(errorText(status, data, '탈퇴하지 못했습니다.'));
    });
  },

  privacy() {},
};

PAGES[document.body.dataset.page]?.();
