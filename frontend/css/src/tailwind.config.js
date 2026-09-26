// 화면들이 Tailwind Play CDN(런타임 생성)으로 쓰던 클래스를 미리 만든 CSS(frontend/css/tw.css)로 바꾼다.
// 페이지별 인라인 설정은 글꼴 확장뿐이었으므로 여기 하나로 모은다. 빌드: scripts/build-css.sh
module.exports = {
  content: ['./frontend/**/*.html', './frontend/js/**/*.js'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', 'sans-serif'],
      },
    },
  },
};
