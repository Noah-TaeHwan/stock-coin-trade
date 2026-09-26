// 메일 링크의 토큰(#t=)을 읽어 메모리에만 두고 주소창에서 지운다.
// 프래그먼트는 서버로 가지 않지만, 주소창·방문 기록·화면 공유에 남지 않게 바로 지운다.
(() => {
  const token = new URLSearchParams(location.hash.slice(1)).get('t');
  window.__authToken = token || '';
  if (location.hash) history.replaceState(null, '', location.pathname);
})();
