# ADR-0002: 해시 고정 의존성 lock, Python 3.11 유지, 알려진 취약점 추적

- 상태: 채택 (2026-09-24, Phase 0)
- 관련: [기반 작업 검증](../evidence/foundation-2026-09-24.md)

## 배경

`python-stock-backend/requirements.txt`는 직접 의존성 14개만 고정한다. 전이 의존성은 빌드하는 날의 최신 버전이 설치된다.

- 2026-09-24에 Python 3.11로 새로 설치하면 pandas 3.0.6, numpy 2.4.6이 들어왔다.
  - pandas는 yfinance 0.2.54의 `pandas>=1.3.0`로, numpy는 qdrant-client 1.17.1의 `numpy>=1.21`로 들어오며, 둘 다 상한이 없다(PyPI 메타데이터).
- numpy 2.5.3은 `requires_python >=3.12`라서 3.11 이미지에는 설치되지 않는다.
- 결과적으로 같은 커밋이라도 빌드 날짜에 따라 메이저 버전이 다른 라이브러리가 들어갈 수 있었다.

## 결정

1. **lock 도구는 uv(`uv pip compile`)**
   - 이미 설치돼 있고, requirements 형식 입력을 그대로 받으며, `--universal`로 플랫폼 독립 lock을 만든다.
   - 런타임 lock: `python-stock-backend/requirements.lock`(81개 패키지, 해시 포함)
   - 개발 lock: `requirements-dev.lock`(105개). 런타임 lock을 `--constraint`로 걸어 공통 패키지 버전이 같게 한다(81개 모두 일치 확인).
2. **설치는 pip 해시 검사 모드**(`--require-hashes`)로 한다. Docker와 CI 모두 같다. pip 문서상 이 모드에서는 모든 요구사항과 의존성이 `==`로 고정되고 해시가 있어야 한다.
3. **Python은 3.11 유지**
   - Phase 0은 동작 보존이 목표라 런타임 버전을 바꾸지 않는다.
   - `--universal` lock에는 3.12 이상용 분기(numpy 2.5.3)도 들어 있어, 전환할 때 lock을 다시 만들 필요가 적다.
   - 3.12 전환은 numpy·pandas 의존이 커지는 Phase 3(`src/quantlab`) 착수 전에 다시 결정한다.
4. **직접 의존성 버전은 그대로 둔다**: CVE 수정용 업그레이드는 Phase 1-H에서 한다.
5. **알려진 취약점 추적**
   - `pip-audit --require-hashes -r python-stock-backend/requirements.lock` 결과 5개 패키지, 고유 ID 26건이 나왔다(2026-09-24).
   - 이 목록을 `.github/pip-audit-known-vulns.txt`에 패키지·CVE·수정 버전과 함께 기록하고, CI는 이 ID만 `--ignore-vuln`으로 넘긴다.
   - 따라서 **목록에 없는 새 취약점이 생기면 CI가 실패한다.** 항목은 업그레이드와 함께 지우고, 추적 계획 없이 추가하지 않는다.

| 패키지 | 원인 | 수정 방향(Phase 1-H) |
|---|---|---|
| Flask 3.0.3 | 직접 고정 | 3.1.3 이상 |
| flask-cors 4.0.1 | 직접 고정 | 6.0.0 이상(동작 변경 검토 필요) |
| requests 2.32.3 | 직접 고정 | 2.33.0 이상 |
| python-dotenv 1.0.1 | 직접 고정 | 1.2.2 이상 |
| pillow 11.3.0 | 사슬: qdrant-client[fastembed] 1.17.1 → fastembed `<0.8`(0.7.4) → pillow `<12.0` | qdrant-client·fastembed 0.8.x 동반 업그레이드. fastembed 0.8.1은 pillow `<13.0` 허용(PyPI) |

## 결과

- 같은 커밋이면 같은 패키지 집합이 설치된다. lock 설치 환경에서 단위 테스트 54개와 통합 테스트 4개가 통과했고, lock 기반 이미지로 전체 스택 스모크 테스트를 했다.
- 의존성을 바꿀 때는 `requirements.txt`를 고치고 lock 두 개를 다시 생성해야 한다. 명령은 `requirements-dev.in` 머리말에 있다.
- 미검증: `--universal` lock에는 aarch64 휠 해시도 들어 있지만, ARM64(Noah의 Mac Docker) 빌드는 이번에 실행하지 않았다.
  - 2026-09-25 확인: Noah의 Mac Docker(aarch64)에서 `compose.portfolio.yml` 스택 이미지 빌드와 기동이 성공했다.

## 후속 (2026-09-25, Phase 1-4)

위 표의 업그레이드를 모두 적용했다. 이제 `pip-audit`는 추적 목록 없이 `No known vulnerabilities found`를 출력하고, 추적 목록은 비어 있다. 자세한 내용은 [검증 기록](../evidence/containers-nginx-deps-2026-09-25.md)에 있다.

| 패키지 | 이전 | 이후 |
|---|---|---|
| Flask | 3.0.3 | 3.1.3 |
| flask-cors | 4.0.1 | 6.0.5 |
| requests | 2.32.3 | 2.34.2 |
| python-dotenv | 1.0.1 | 1.2.3 |
| qdrant-client[fastembed] | 1.17.1 | 1.19.1(fastembed 0.7.4 → 0.8.1, pillow 11.3.0 → 12.3.0) |

- qdrant-client 1.19.1에서는 `set_model`·`add`·`query`가 없어졌다. 실제로 초기화가 `AttributeError`로 실패하는 것을 확인했다.
- 그래서 `qdrant_service`를 README의 로컬 추론 방식(`models.Document` + `upsert` + `query_points`)으로 옮겼다.
- 같은 질의의 상위 결과와 점수가 옛 클라이언트와 같았다.

## 근거 (조회일 2026-09-24)

- uv `pip compile`(requirements 입력, 여러 입력 파일, `--universal`) — https://docs.astral.sh/uv/pip/compile/
- pip 해시 검사 모드 — https://pip.pypa.io/en/stable/topics/secure-installs/
- pip-audit `--require-hashes`, `--ignore-vuln`, 종료 코드 — https://github.com/pypa/pip-audit
- PyPI JSON: numpy 2.5.3 `requires_python >=3.12`, pandas 3.0.6 `>=3.11`, fastembed 0.7.4·0.8.1과 qdrant-client 1.17.1의 `requires_dist`, 패키지별 `vulnerabilities`
