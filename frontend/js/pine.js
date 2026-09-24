const PINE_EXAMPLES = {
ma: `//@version=5
strategy("이동평균 교차", overlay=true)

fast = ta.sma(close, 5)
slow = ta.sma(close, 20)
longCondition = ta.crossover(fast, slow)
shortCondition = ta.crossunder(fast, slow)

if longCondition
    strategy.entry("Long", strategy.long)
if shortCondition
    strategy.close("Long")`,
"tp-sl": `//@version=5
strategy("3% 익절 · 1.5% 손절", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=10)

tpPercent = input.float(3.0, title="익절 비율 (%)", minval=0.1, step=0.1) / 100
slPercent = input.float(1.5, title="손절 비율 (%)", minval=0.1, step=0.1) / 100
fastMA = ta.sma(close, 14)
slowMA = ta.sma(close, 28)
longCondition = ta.crossover(fastMA, slowMA)

if longCondition
    strategy.entry("Long", strategy.long)

if strategy.position_size > 0
    longTP = strategy.position_avg_price * (1 + tpPercent)
    longSL = strategy.position_avg_price * (1 - slPercent)
    strategy.exit("Long 청산", from_entry="Long", limit=longTP, stop=longSL)`,
rsi: `//@version=5
strategy("RSI 반전", overlay=true)

rsiValue = ta.rsi(close, 14)
longCondition = ta.crossover(rsiValue, 30)
exitCondition = ta.crossunder(rsiValue, 70)

if longCondition
    strategy.entry("Long", strategy.long)
if exitCondition
    strategy.close("Long")`
};
const PINE_EXAMPLE = PINE_EXAMPLES.ma;

let pineChart, pineCandles, pineFast, pineSlow;
let pineStocks = [], pineData = [], pinePeriod = '1y', pineSignal = null, pinePosition = null;
const $ = id => document.getElementById(id);
const fmt = number => Number(number || 0).toLocaleString('ko-KR') + '원';

async function pineRequest(path, options = {}) {
  const res = await fetch((window.APP_CONFIG?.apiBase || '') + path, { credentials: 'include', ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || '요청을 처리하지 못했습니다.');
  return data;
}
function sma(values, length) { return values.map((_, i) => i < length - 1 ? null : values.slice(i - length + 1, i + 1).reduce((sum, value) => sum + value, 0) / length); }
function ema(values, length) { const k = 2 / (length + 1); let previous = values[0]; return values.map((value, i) => previous = i ? value * k + previous * (1 - k) : value); }
function rsi(values, length) { return values.map((_, i) => { if (i < length) return null; let gain = 0, loss = 0; for (let j = i - length + 1; j <= i; j++) { const diff = values[j] - values[j - 1]; if (diff >= 0) gain += diff; else loss -= diff; } return loss === 0 ? 100 : 100 - 100 / (1 + gain / loss); }); }
function crossed(a, b, direction) { const i = a.length - 1; if (i < 1 || a[i] == null || b[i] == null || a[i - 1] == null || b[i - 1] == null) return false; return direction === 'up' ? a[i] > b[i] && a[i - 1] <= b[i - 1] : a[i] < b[i] && a[i - 1] >= b[i - 1]; }

function initChart() {
  const el = $('pineChart');
  pineChart = LightweightCharts.createChart(el, termChartOptions());
  pineCandles = pineChart.addCandlestickSeries(termCandleColors());
  pineFast = pineChart.addLineSeries({ color:'#FFD60A', lineWidth:2, lastValueVisible:false, priceLineVisible:false });
  pineSlow = pineChart.addLineSeries({ color:'#B39DFF', lineWidth:2, lastValueVisible:false, priceLineVisible:false });
  new ResizeObserver(() => pineChart.resize(el.clientWidth, el.clientHeight)).observe(el);
}
async function loadStocks() {
  const data = await pineRequest('/api/stocks/list?limit=30'); pineStocks = data.stocks || [];
  const select = $('pineSymbol'); select.innerHTML = pineStocks.map(stock => `<option value="${stock.symbol}">${stock.name} (${stock.symbol})</option>`).join('');
  const requested = new URLSearchParams(location.search).get('symbol'); if (requested && pineStocks.some(stock => stock.symbol === requested)) select.value = requested;
  select.addEventListener('change', loadChart); await loadChart();
}
async function loadChart() {
  const symbol = $('pineSymbol').value; if (!symbol) return;
  $('pineLog').textContent = '차트 데이터를 불러오는 중...';
  try {
    const [chart, quote, positions] = await Promise.all([pineRequest(`/api/stocks/chart?symbol=${encodeURIComponent(symbol)}&period=${pinePeriod}`), pineRequest(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`), pineRequest('/api/stocks/positions')]);
    pineData = (chart.data || []).map(d => ({ time:Math.floor(d.x / 1000), open:d.o, high:d.h, low:d.l, close:d.c })).sort((a,b) => a.time - b.time);
    pineCandles.setData(pineData); pineChart.timeScale().fitContent();
    const stock = pineStocks.find(item => item.symbol === symbol); $('pineStockMeta').textContent = stock ? `${stock.market} · ${stock.sector || '기타'}` : ''; $('pinePrice').textContent = fmt(quote.price);
    pinePosition = (positions.positions || []).find(position => position.symbol === symbol) || null;
    $('pineLog').textContent = `${pineData.length}개 봉을 불러왔습니다.${pinePosition ? ` 보유: ${pinePosition.quantity}주 · 평균 ${fmt(pinePosition.avgPrice)}` : ' 현재 보유 포지션 없음'}\n스크립트를 실행해 최신 신호를 계산하세요.`; pineSignal = null; renderSignal();
  } catch (error) { $('pineLog').textContent = error.message; }
}
function parseIndicators(script, closes) {
  const vars = { close: closes }, inputs = {}; const lines = script.split('\n');
  for (const line of lines) {
    const input = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*input\.float\(\s*([\d.]+)/i);
    if (input) inputs[input[1]] = Number(input[2]) / (/\/\s*100\b/.test(line) ? 100 : 1);
    const match = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*ta\.(sma|ema|rsi)\(close\s*,\s*(\d+)\s*\)/i); if (!match) continue;
    vars[match[1]] = match[2].toLowerCase() === 'sma' ? sma(closes, +match[3]) : match[2].toLowerCase() === 'ema' ? ema(closes, +match[3]) : rsi(closes, +match[3]);
  }
  return { vars, inputs };
}
function evaluateStrategy() {
  const script = $('pineScript').value, closes = pineData.map(item => item.close); if (closes.length < 2) return;
  try {
    const { vars, inputs } = parseIndicators(script, closes); let conditions = {};
    const series = value => vars[value] || (Number.isFinite(Number(value)) ? Array(closes.length).fill(Number(value)) : null);
    for (const line of script.split('\n')) {
      const m = line.match(/^\s*([A-Za-z_]\w*)\s*=\s*ta\.(crossover|crossunder)\(\s*([A-Za-z_]\w*|[\d.]+)\s*,\s*([A-Za-z_]\w*|[\d.]+)\s*\)/i); if (m) { const left = series(m[3]), right = series(m[4]); if (!left || !right) throw new Error(`${m[1]}에서 정의되지 않은 지표를 사용했습니다.`); conditions[m[1]] = crossed(left, right, m[2].toLowerCase() === 'crossover' ? 'up' : 'down'); }
    }
    let side = null, reason = '최신 봉에서 진입 또는 청산 조건이 충족되지 않았습니다.';
    const sourceLines = script.split('\n');
    sourceLines.forEach((line, index) => { const previous = sourceLines.slice(Math.max(0,index-2), index).join(' '); if (/strategy\.entry\([^\n]*strategy\.long/i.test(line) && Object.entries(conditions).some(([name, value]) => value && new RegExp(`\\b${name}\\b`).test(previous))) { side='BUY'; reason='상승 교차 조건으로 매수 신호가 발생했습니다.'; } if (/strategy\.(close|entry\([^\n]*strategy\.short)/i.test(line) && Object.entries(conditions).some(([name, value]) => value && new RegExp(`\\b${name}\\b`).test(previous))) { side='SELL'; reason='하락 교차/청산 조건으로 매도 신호가 발생했습니다.'; } });
    let riskHtml = '';
    if (/strategy\.exit\s*\(/i.test(script) && pinePosition) {
      const tp = inputs.tpPercent ?? inputs.takeProfitPercent;
      const sl = inputs.slPercent ?? inputs.stopLossPercent;
      if (Number.isFinite(tp) || Number.isFinite(sl)) {
        const avg = Number(pinePosition.avgPrice), latest = pineData.at(-1);
        const tpPrice = Number.isFinite(tp) ? avg * (1 + tp) : null, slPrice = Number.isFinite(sl) ? avg * (1 - sl) : null;
        riskHtml = `${tpPrice ? `<span style="color:var(--up);">익절 ${fmt(Math.round(tpPrice))} (+${(tp * 100).toFixed(1)}%)</span>` : ''}${tpPrice && slPrice ? '<br>' : ''}${slPrice ? `<span style="color:var(--down);">손절 ${fmt(Math.round(slPrice))} (-${(sl * 100).toFixed(1)}%)</span>` : ''}<br><span style="color:var(--muted);">평균 ${fmt(avg)} · 최신 봉 ${fmt(latest.low)} ~ ${fmt(latest.high)}</span>`;
        if (slPrice && latest.low <= slPrice) { side = 'SELL'; reason = `손절가 ${fmt(Math.round(slPrice))}에 도달했습니다.`; }
        else if (tpPrice && latest.high >= tpPrice) { side = 'SELL'; reason = `익절가 ${fmt(Math.round(tpPrice))}에 도달했습니다.`; }
      }
    }
    const indicatorLines = Object.entries(vars).filter(([key]) => key !== 'close').map(([key, values]) => `${key}: ${values.at(-1)?.toFixed(2) ?? '-'}`).join(' · ');
    const fastNames = Object.entries(vars).filter(([key]) => /fast|short/i.test(key)); const slowNames = Object.entries(vars).filter(([key]) => /slow|long/i.test(key));
    pineFast.setData(fastNames[0]?.[1]?.map((value,i) => value == null ? null : ({time:pineData[i].time,value})).filter(Boolean) || []); pineSlow.setData(slowNames[0]?.[1]?.map((value,i) => value == null ? null : ({time:pineData[i].time,value})).filter(Boolean) || []);
    pineSignal = side; if (side === 'SELL' && pinePosition) $('pineQuantity').value = pinePosition.quantity; $('pineLog').textContent = `테스트 완료\n${indicatorLines || '지표 선언 없음'}\n${reason}`; renderSignal(reason, false, riskHtml);
  } catch (error) { pineSignal = null; $('pineLog').textContent = `스크립트를 해석할 수 없습니다: ${error.message}`; renderSignal(error.message, true); }
}
function renderSignal(message = '', isError = false, riskHtml = '') { const label = pineSignal === 'BUY' ? '매수 신호' : pineSignal === 'SELL' ? '매도 신호' : isError ? '검토 필요' : '신호 없음'; $('pineSignal').textContent = label; $('pineSignal').style.color = pineSignal === 'BUY' ? 'var(--up)' : pineSignal === 'SELL' ? 'var(--down)' : 'var(--fg)'; $('pineSignalDetail').textContent = message || '스크립트를 실행해 신호를 확인하세요.'; $('pineOrder').disabled = !pineSignal; $('pineOrder').textContent = pineSignal ? `${pineSignal === 'BUY' ? '매수' : '매도'} 신호로 모의주문 실행` : '신호대로 모의주문 실행'; $('pineRiskLevels').style.display = riskHtml ? 'block' : 'none'; $('pineRiskLevels').innerHTML = riskHtml; }
async function executePineOrder() { const quantity = Number($('pineQuantity').value); if (!pineSignal || !Number.isInteger(quantity) || quantity < 1) return; if (!confirm(`${$('pineSymbol').selectedOptions[0].textContent} ${quantity}주를 ${pineSignal === 'BUY' ? '매수' : '매도'}하시겠습니까?`)) return; const message = $('pineOrderMessage'); try { const result = await pineRequest('/api/stocks/orders/pine', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:$('pineSymbol').value,side:pineSignal,quantity})}); message.style.color='var(--up)'; message.textContent = `${pineSignal === 'BUY' ? '매수' : '매도'} 완료 · 체결가 ${fmt(result.price)}`; await loadChart(); evaluateStrategy(); } catch (error) { message.style.color='var(--down)'; message.textContent=error.message; } }
document.addEventListener('DOMContentLoaded', async () => { if (!await initPage({ requireAuth:true })) return; $('pineScript').value = PINE_EXAMPLE; initChart(); $('pineExample').addEventListener('click', () => { $('pineScript').value = PINE_EXAMPLES[$('pineExampleSelect').value]; evaluateStrategy(); }); $('pineEvaluate').addEventListener('click', evaluateStrategy); $('pineOrder').addEventListener('click', executePineOrder); $('pinePeriods').addEventListener('click', event => { const btn=event.target.closest('[data-period]'); if (!btn) return; pinePeriod=btn.dataset.period; document.querySelectorAll('.period').forEach(item=>item.classList.toggle('active',item===btn)); loadChart(); }); try { await loadStocks(); } catch (error) { $('pineLog').textContent=error.message; } });
