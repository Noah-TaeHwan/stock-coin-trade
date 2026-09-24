const LAB_TEMPLATES={
  indicator:`//@version=6
indicator("20일 이동평균선", overlay=true)

ma20 = ta.sma(close, 20)
plot(ma20, color=color.orange, linewidth=2)`,
  ma:`//@version=6
strategy("5일선과 20일선 교차", overlay=true)

fast = ta.sma(close, 5)
slow = ta.sma(close, 20)
buy = ta.crossover(fast, slow)
sell = ta.crossunder(fast, slow)

if buy
    strategy.entry("Long", strategy.long)
if sell
    strategy.close("Long")`,
  rsi:`//@version=6
strategy("RSI 30/70 반전", overlay=false)

rsiValue = ta.rsi(close, 14)
buy = ta.crossover(rsiValue, 30)
sell = ta.crossunder(rsiValue, 70)

if buy
    strategy.entry("Long", strategy.long)
if sell
    strategy.close("Long")`
};
const META={indicator:{title:'20일 이동평균선',plain:'주황색 선은 최근 20개 가격의 평균입니다. 가격이 평균선 위에 있으면 최근 흐름이 상대적으로 강하고, 아래에 있으면 약하다고 읽는 기초 지표입니다.'},ma:{title:'이동평균선 교차',plain:'짧은 5일선이 긴 20일선을 위로 통과한 곳이 BUY, 아래로 통과한 곳이 SELL입니다. 선이 자주 교차하면 횡보장에서 신호가 많아질 수 있습니다.'},rsi:{title:'RSI 과매도·과매수',plain:'RSI가 낮은 30 구간을 벗어나면 BUY, 높은 70 구간에서 내려오면 SELL로 표시했습니다. RSI 하나만으로 실제 주문하지 않고 추세와 함께 확인합니다.'}};
const $=id=>document.getElementById(id);const prices=Array.from({length:90},(_,i)=>Number((100+i*.18+Math.sin(i*.31)*5.5+Math.sin(i*.09)*3).toFixed(2)));const times=prices.map((_,i)=>{const d=new Date(Date.UTC(2026,0,2+i));return d.toISOString().slice(0,10)});const fmt=v=>v==null?'-':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2});
const sma=(values,n)=>values.map((_,i)=>i<n-1?null:values.slice(i-n+1,i+1).reduce((a,b)=>a+b,0)/n);const ema=(values,n)=>{const k=2/(n+1);let p=values[0];return values.map((v,i)=>p=i?v*k+p*(1-k):v)};const rsi=(values,n)=>values.map((_,i)=>{if(i<n)return null;let g=0,l=0;for(let j=i-n+1;j<=i;j++){const d=values[j]-values[j-1];if(d>=0)g+=d;else l-=d}return l===0?100:100-100/(1+g/l)});const fixed=v=>Array(prices.length).fill(Number(v));const cross=(a,b,i,up)=>i>0&&a[i]!=null&&b[i]!=null&&a[i-1]!=null&&b[i-1]!=null&&(up?a[i]>b[i]&&a[i-1]<=b[i-1]:a[i]<b[i]&&a[i-1]>=b[i-1]);
let selected='indicator',chart,priceSeries,line1,line2;
function parse(code){const issues=[];if(!/^\s*\/\/\@version=(5|6)\s*$/m.test(code))issues.push('첫 줄에 //@version=6을 넣어 주세요.');const kind=/\bstrategy\s*\(/.test(code)?'strategy':/\bindicator\s*\(/.test(code)?'indicator':null;if(!kind)issues.push('indicator() 또는 strategy()가 필요합니다.');const vars={close:prices},indicators=[];for(const m of code.matchAll(/^\s*([A-Za-z_]\w*)\s*=\s*ta\.(sma|ema|rsi)\(\s*close\s*,\s*(\d+)\s*\)/gmi)){const n=Number(m[3]);if(n<2||n>80)issues.push(`${m[1]} 기간은 2~80으로 입력하세요.`);else{vars[m[1]]=m[2].toLowerCase()==='sma'?sma(prices,n):m[2].toLowerCase()==='ema'?ema(prices,n):rsi(prices,n);indicators.push(m[1])}}const conditions={};for(const m of code.matchAll(/^\s*([A-Za-z_]\w*)\s*=\s*ta\.(crossover|crossunder)\(\s*([A-Za-z_]\w*|\d+(?:\.\d+)?)\s*,\s*([A-Za-z_]\w*|\d+(?:\.\d+)?)\s*\)/gmi)){const a=vars[m[3]]||(Number.isFinite(Number(m[3]))?fixed(m[3]):null),b=vars[m[4]]||(Number.isFinite(Number(m[4]))?fixed(m[4]):null);if(!a||!b)issues.push(`${m[1]}에 사용한 지표 이름을 확인하세요.`);else conditions[m[1]]=prices.map((_,i)=>cross(a,b,i,m[2].toLowerCase()==='crossover'))}if(kind==='strategy'&&!Object.keys(conditions).length)issues.push('전략에는 crossover 또는 crossunder 조건이 필요합니다.');return{issues,kind,vars,indicators,conditions}}
function initChart(){chart=LightweightCharts.createChart($('pineChart'),termChartOptions({autoSize:true,localization:{locale:'ko-KR',priceFormatter:p=>fmt(p)}}));priceSeries=chart.addLineSeries({color:'#4FC3F7',lineWidth:2,title:'가격'});line1=chart.addLineSeries({color:'#f59e0b',lineWidth:2,priceLineVisible:false,lastValueVisible:true});line2=chart.addLineSeries({color:'#8b5cf6',lineWidth:2,priceLineVisible:false,lastValueVisible:true});priceSeries.setData(prices.map((value,i)=>({time:times[i],value})))}
function strategySignals(parsed,code){const entries=[],exits=[];let current=null;code.split('\n').forEach(line=>{const condition=line.match(/^\s*if\s+([A-Za-z_]\w*)/);if(condition)current=condition[1];if(/strategy\.entry\([^\n]*strategy\.long/i.test(line)&&parsed.conditions[current])entries.push(current);if(/strategy\.close\s*\(/i.test(line)&&parsed.conditions[current])exits.push(current)});let holding=false,entry=0,equity=100,peak=100,maxDd=0;const signals=[],returns=[];prices.forEach((price,i)=>{const buy=entries.some(n=>parsed.conditions[n][i]),sell=exits.some(n=>parsed.conditions[n][i]);if(!holding&&buy){holding=true;entry=price;signals.push({i,type:'BUY'})}else if(holding&&sell){const ret=(price/entry-1)*100;returns.push(ret);equity*=1+ret/100;holding=false;signals.push({i,type:'SELL'})}const marked=holding?equity*price/entry:equity;peak=Math.max(peak,marked);maxDd=Math.min(maxDd,(marked/peak-1)*100)});return{signals,returns,equity,holding,maxDd}}
function renderTable(parsed,signals){const indices=signals.length?signals.slice(-12).map(s=>s.i):Array.from({length:8},(_,n)=>prices.length-8+n);$('signalRows').innerHTML=indices.map(i=>{const signal=signals.find(s=>s.i===i)?.type||(parsed.kind==='indicator'?'지표':'-');const a=parsed.indicators[0]?parsed.vars[parsed.indicators[0]][i]:null,b=parsed.indicators[1]?parsed.vars[parsed.indicators[1]][i]:null;return `<tr><td>${i+1}봉</td><td>${fmt(prices[i])}</td><td>${fmt(a)}</td><td>${fmt(b)}</td><td class="${signal==='BUY'?'buy':signal==='SELL'?'sell':''}">${signal}</td></tr>`}).join('')}
function runLab(){const code=$('pineLabCode').value.trim()||LAB_TEMPLATES[selected];$('pineLabCode').value=code;const parsed=parse(code);if(parsed.issues.length){$('labStatus').textContent=`수정할 부분: ${parsed.issues.join(' ')}`;$('plainResult').textContent='코드의 안내 문구를 확인하고 숫자 또는 지표 이름을 수정하세요.';return}const result=strategySignals(parsed,code),first=parsed.indicators[0],second=parsed.indicators[1];line1.setData(first?parsed.vars[first].map((value,i)=>value==null?null:{time:times[i],value}).filter(Boolean):[]);line2.setData(second?parsed.vars[second].map((value,i)=>value==null?null:{time:times[i],value}).filter(Boolean):[]);priceSeries.setMarkers(result.signals.map(s=>({time:times[s.i],position:s.type==='BUY'?'belowBar':'aboveBar',color:s.type==='BUY'?termColors().up:termColors().down,shape:s.type==='BUY'?'arrowUp':'arrowDown',text:s.type})));chart.timeScale().fitContent();const latest=result.signals.at(-1);$('chartTitle').textContent=`${META[selected].title} 결과`;$('labStatus').textContent=parsed.kind==='indicator'?`계산 완료: ${first}의 마지막 값은 ${fmt(parsed.vars[first]?.at(-1))}입니다.`:`계산 완료: BUY/SELL 신호 ${result.signals.length}개, 완료 거래 ${result.returns.length}건입니다.`;$('plainResult').textContent=META[selected].plain;$('lastClose').textContent=fmt(prices.at(-1));$('lastSignal').textContent=parsed.kind==='indicator'?'지표만 표시':latest?`${latest.type} (${latest.i+1}봉)`:'신호 없음';$('lastSignal').className=latest?.type==='BUY'?'buy':latest?.type==='SELL'?'sell':'';$('tradeCount').textContent=parsed.kind==='indicator'?'없음':`${result.returns.length}건`;$('strategyReturn').textContent=parsed.kind==='indicator'?'계산 안 함':`${(result.equity-100).toFixed(2)}%`;$('maxDrawdown').textContent=parsed.kind==='indicator'?'계산 안 함':`${result.maxDd.toFixed(2)}%`;$('barCount').textContent=`${prices.length}개`;renderTable(parsed,result.signals)}
function selectTemplate(name,run=true){selected=name;const editor=$('pineLabCode');editor.value=LAB_TEMPLATES[name];editor.defaultValue=LAB_TEMPLATES[name];document.querySelectorAll('.example').forEach(button=>button.classList.toggle('selected',button.dataset.template===name));$('selectedHint').textContent=`선택됨: ${META[name].title}`;if(run)runLab()}
document.addEventListener('DOMContentLoaded',async()=>{await initPage();initChart();document.querySelectorAll('.example').forEach(button=>button.addEventListener('click',()=>selectTemplate(button.dataset.template,true)));$('runLab').addEventListener('click',runLab);$('runCode').addEventListener('click',runLab);$('reloadCode').addEventListener('click',()=>selectTemplate(selected,false));selectTemplate('indicator',true)});
