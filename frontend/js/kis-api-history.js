let kisHistoryGrid;
let kisHistoryRows = [];
const kh = id => document.getElementById(id);
const khDate = value => value ? new Date(value).toLocaleString('ko-KR', { hour12:false }) : '-';

function resultBadge(value) {
  const color = value ? '#15803D' : '#E11D48';
  return `<b style="color:${color}">${value ? '성공' : '실패'}</b>`;
}

function createGrid() {
  return agGrid.createGrid(kh('grid'), {
    columnDefs: [
      { headerName:'호출 시각', field:'calledAt', minWidth:170, sort:'desc', valueFormatter:p => khDate(p.value) },
      { headerName:'계층', field:'layer', minWidth:112, filter:true },
      { headerName:'TR ID', field:'trId', minWidth:125, valueFormatter:p => p.value || '-' },
      { headerName:'시도', field:'attempt', width:70, type:'rightAligned', valueFormatter:p => p.value || '-' },
      { headerName:'작업', field:'operation', minWidth:175, flex:1, tooltipField:'operation' },
      { headerName:'방식', field:'method', width:78 },
      { headerName:'HTTP', field:'status', width:80, type:'rightAligned' },
      { headerName:'결과', field:'success', width:82, cellRenderer:p => resultBadge(p.value) },
      { headerName:'소요시간', field:'durationMs', minWidth:100, type:'rightAligned', valueFormatter:p => p.value == null ? '-' : `${Number(p.value).toLocaleString()} ms` },
      { headerName:'API 경로', field:'path', minWidth:260, flex:1.35, tooltipField:'path' },
      { headerName:'요약·오류', field:'summary', minWidth:230, flex:1.2, tooltipField:'summary' },
    ],
    rowData: [],
    defaultColDef:{ sortable:true, filter:true, resizable:true, suppressHeaderMenuButton:true },
    pagination:true, paginationPageSize:25, paginationPageSizeSelector:[25,50,100],
    rowSelection:{ mode:'singleRow', enableClickSelection:true, checkboxes:false, headerCheckbox:false },
    overlayNoRowsTemplate:'<span style="padding:16px;color:#64748B">아직 KIS API 호출 기록이 없습니다.</span>',
    onRowClicked:event => loadDetail(event.data.id),
  });
}

function applyFilters() {
  const layer = kh('layer').value;
  const result = kh('result').value;
  const rows = kisHistoryRows.filter(row => (!layer || row.layer === layer) && (!result || row.success === (result === 'success')));
  kisHistoryGrid.setGridOption('rowData', rows);
  kisHistoryGrid.setGridOption('quickFilterText', kh('filter').value);
  kh('status').textContent = `${rows.length.toLocaleString()}건 표시 · 로그인한 내 호출만 조회`;
}

async function loadDetail(id) {
  kh('detail').textContent = '상세 기록을 불러오는 중…';
  try {
    const response = await apiFetch(`/api/api-usage/history/${id}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '상세 기록을 불러오지 못했습니다.');
    const row = data.log;
    let requestMeta = row.requestMeta;
    let responseBody = row.responseBody;
    try { requestMeta = requestMeta ? JSON.parse(requestMeta) : null; } catch {}
    try { responseBody = responseBody ? JSON.parse(responseBody) : null; } catch {}
    kh('detail').textContent = JSON.stringify({
      calledAt: row.calledAt, layer: row.layer, operation: row.operation,
      method: row.method, path: row.path, httpStatus: row.status,
      success: row.success, durationMs: row.durationMs,
      request: requestMeta, response: responseBody,
    }, null, 2);
  } catch (error) {
    kh('detail').textContent = `상세 조회 실패\n${error.message}`;
  }
}

async function loadHistory() {
  kh('status').textContent = 'KIS 호출 이력을 불러오는 중…';
  try {
    const response = await apiFetch('/api/api-usage/kis-history?limit=1000');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'KIS 호출 이력을 불러오지 못했습니다.');
    kisHistoryRows = data.history || [];
    const summary = data.summary || {};
    kh('total').textContent = Number(summary.total || 0).toLocaleString();
    kh('outbound').textContent = Number(summary.outbound || 0).toLocaleString();
    kh('success').textContent = Number(summary.success || 0).toLocaleString();
    kh('failure').textContent = Number(summary.failure || 0).toLocaleString();
    kh('average').textContent = summary.averageMs == null ? '-' : `${Number(summary.averageMs).toLocaleString()} ms`;
    applyFilters();
  } catch (error) {
    kh('status').textContent = error.message;
  }
}

(async () => {
  const user = await initPage({ requireAuth:true });
  if (!user) return;
  if (!window.agGrid) { kh('status').textContent = 'Grid 라이브러리를 불러오지 못했습니다.'; return; }
  kisHistoryGrid = createGrid();
  kh('filter').addEventListener('input', applyFilters);
  kh('layer').addEventListener('change', applyFilters);
  kh('result').addEventListener('change', applyFilters);
  kh('refresh').addEventListener('click', loadHistory);
  await loadHistory();
})();
