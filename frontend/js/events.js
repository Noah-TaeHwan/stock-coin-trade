/* 공시 레이더 화면. 서버 /api/disclosures가 저장해 둔 DART 공시와 판정(규칙·Jev)을 그린다.
   교육용 분류이며 투자 권유가 아니다. 주문 기능은 없다. */

const DISC_POLL_MS = 60_000;

const disc = {
  day: '',          // YYYY-MM-DD, 비우면 서버가 오늘(KST)을 쓴다
  symbol: '',
  kind: '',
  riskOnly: false,
  kinds: {},        // 유형 id → 화면 이름(서버가 준다)
  items: [],
};
let discTimer = null;

const discEsc = escapeHtml;
const pct = p => typeof p === 'number' && Number.isFinite(p) ? `${Math.round(p * 100)}%` : '';

/**
 * 오늘 날짜(KST)를 YYYY-MM-DD로 돌려준다.
 * @returns {string}
 */
function kstToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(new Date());
}

/**
 * 현재 필터로 API 주소를 만든다. 유형은 화면에서 거르므로 보내지 않는다(유형별 건수를 함께 보여 주려고).
 * @returns {string}
 */
function discQuery() {
  const params = new URLSearchParams();
  if (disc.day) params.set('date', disc.day);
  if (/^\d{6}$/.test(disc.symbol)) params.set('symbol', disc.symbol);
  if (disc.riskOnly) params.set('risk', '1');
  params.set('limit', '500');
  return `/api/disclosures?${params}`;
}

/**
 * 서버에서 공시를 읽어 다시 그린다.
 * @returns {Promise<void>}
 */
async function loadDisclosures() {
  const live = document.getElementById('discLive');
  try {
    const res = await apiFetch(discQuery());
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
    disc.items = Array.isArray(body.items) ? body.items : [];
    disc.kinds = body.kinds || disc.kinds;
    if (body.attribution) document.getElementById('discSource').textContent = body.attribution;
    live?.classList.remove('is-off');
    renderKindOptions();
    renderDisclosures();
  } catch (err) {
    live?.classList.add('is-off');
    document.getElementById('discBody').innerHTML =
      `<tr><td class="empty" colspan="6">공시를 불러오지 못했습니다: ${discEsc(err.message)}</td></tr>`;
  }
}

/** 유형 선택 상자를 서버가 준 유형 목록으로 채운다. */
function renderKindOptions() {
  const select = document.getElementById('kind');
  if (select.options.length > 1) return;
  for (const [key, label] of Object.entries(disc.kinds)) select.add(new Option(label, key));
  select.value = disc.kind;
}

/**
 * 판정 칸: 규칙이면 '규칙', Jev면 'Jev'와 모델 판단 확률.
 * @param {object} item API 항목
 * @returns {string} HTML
 */
function judgedCell(item) {
  if (item.judgedBy !== 'jev') return '<span class="by">규칙</span>';
  const probs = [item.kindProb != null ? `유형 ${pct(item.kindProb)}` : '', item.riskProb != null ? `위험 ${pct(item.riskProb)}` : '']
    .filter(Boolean).join(' · ');
  return `<span class="by" title="TypeSafe Jev 모델 판단 확률">Jev ${discEsc(probs)}</span>`;
}

/** 목록과 유형별 건수를 그린다. */
function renderDisclosures() {
  const rows = disc.kind ? disc.items.filter(item => item.kind === disc.kind) : disc.items;
  const riskCount = disc.items.filter(item => item.risk).length;
  document.getElementById('discCount').textContent =
    `${rows.length}건 표시 · 전체 ${disc.items.length}건 · 위험 ${riskCount}건`;
  document.getElementById('discTitle').textContent = `${disc.day || kstToday()} 공시${disc.symbol ? ` · ${disc.symbol}` : ''}`;

  document.getElementById('discBody').innerHTML = rows.length ? rows.map(item => {
    const code = /^\d{6}$/.test(item.stockCode || '') ? item.stockCode : '';
    // 원문 링크는 서버 문자열 대신 접수번호로 다시 만든다(같은 DART 주소만 연다).
    const link = /^\d{14}$/.test(item.rceptNo || '') ? `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${item.rceptNo}` : '';
    const title = link
      ? `<a href="${link}" target="_blank" rel="noopener noreferrer">${discEsc(item.reportName)}</a>`
      : discEsc(item.reportName);
    return `<tr class="${item.risk ? 'is-risk' : ''}">
      <td>${discEsc(item.firstSeenKst || '-')}</td>
      <td class="txt who">${discEsc(item.corpName)}<small>${discEsc(item.market || '')}${code ? ` · <a href="/events.html?symbol=${code}">${code}</a>` : ''}</small></td>
      <td class="txt">${title}${item.corrected ? '<small>정정 공시</small>' : ''}</td>
      <td class="txt">${discEsc(item.kindLabel || item.kind)}</td>
      <td>${item.risk ? '<span class="flag">⚠ 위험</span>' : '-'}</td>
      <td>${judgedCell(item)}</td>
    </tr>`;
  }).join('') : '<tr><td class="empty" colspan="6">조건에 맞는 공시가 없습니다. 휴일이거나 수집기가 아직 돌지 않았을 수 있습니다.</td></tr>';

  const counts = {};
  for (const item of disc.items) counts[item.kind] = (counts[item.kind] || 0) + 1;
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  document.getElementById('kindBody').innerHTML = sorted.length ? sorted.map(([key, n]) =>
    `<tr data-kind="${discEsc(key)}" class="${key === disc.kind ? 'is-selected' : ''}" tabindex="0" role="button" aria-pressed="${key === disc.kind}">
      <td>${discEsc(disc.kinds[key] || key)}</td><td>${n}</td></tr>`).join('')
    : '<tr><td class="empty">-</td></tr>';
}

/** 현재 필터를 주소창에 남긴다(새로 고침·공유용). */
function syncUrl() {
  const params = new URLSearchParams();
  if (disc.day) params.set('date', disc.day);
  if (disc.symbol) params.set('symbol', disc.symbol);
  if (disc.kind) params.set('kind', disc.kind);
  if (disc.riskOnly) params.set('risk', '1');
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}`);
}

/** 필터·유형 요약의 이벤트를 연결한다. */
function bindDiscEvents() {
  const day = document.getElementById('day');
  const symbol = document.getElementById('symbol');
  const kind = document.getElementById('kind');
  const riskOnly = document.getElementById('riskOnly');
  day.value = disc.day || kstToday();
  symbol.value = disc.symbol;
  riskOnly.checked = disc.riskOnly;

  day.addEventListener('change', () => { disc.day = day.value === kstToday() ? '' : day.value; syncUrl(); loadDisclosures(); });
  symbol.addEventListener('input', () => {
    const value = symbol.value.replace(/\D/g, '').slice(0, 6);
    symbol.value = value;
    if (value.length === 0 || value.length === 6) { disc.symbol = value; syncUrl(); loadDisclosures(); }
  });
  kind.addEventListener('change', () => { disc.kind = kind.value; syncUrl(); renderDisclosures(); });
  riskOnly.addEventListener('change', () => { disc.riskOnly = riskOnly.checked; syncUrl(); loadDisclosures(); });
  document.getElementById('discFilters').addEventListener('submit', event => event.preventDefault());

  const pickKind = row => {
    disc.kind = disc.kind === row.dataset.kind ? '' : row.dataset.kind;
    kind.value = disc.kind;
    syncUrl();
    renderDisclosures();
  };
  const kindBody = document.getElementById('kindBody');
  kindBody.addEventListener('click', event => { const row = event.target.closest('tr[data-kind]'); if (row) pickKind(row); });
  kindBody.addEventListener('keydown', event => {
    const row = event.target.closest('tr[data-kind]');
    if (row && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); pickKind(row); }
  });
}

/** 1분마다 다시 읽는다(수집기는 5분마다 돈다). */
function startDiscPolling() {
  clearInterval(discTimer);
  discTimer = setInterval(loadDisclosures, DISC_POLL_MS);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { clearInterval(discTimer); return; }
  loadDisclosures();
  startDiscPolling();
});

document.addEventListener('DOMContentLoaded', async () => {
  const params = new URLSearchParams(location.search);
  const symbol = params.get('symbol') || '';
  const day = params.get('date') || '';
  if (/^\d{6}$/.test(symbol)) disc.symbol = symbol;
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) disc.day = day;
  disc.kind = /^[a-z_]{2,30}$/.test(params.get('kind') || '') ? params.get('kind') : '';
  disc.riskOnly = params.get('risk') === '1';
  await initPage();
  bindDiscEvents();
  await loadDisclosures();
  startDiscPolling();
});
