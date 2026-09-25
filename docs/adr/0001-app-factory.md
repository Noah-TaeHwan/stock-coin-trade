# ADR-0001: 앱 팩토리와 프로세스 분리(init·web·worker)

- 상태: 채택 (2026-09-24, Phase 0)
- 관련: [기반 작업 검증](../evidence/foundation-2026-09-24.md)

## 배경

원본 `python-stock-backend/app.py`는 모듈 수준에서 Flask 앱을 만들고, import하는 순간 다음을 실행했다(원본 `app.py:88-98`).
- MariaDB 테이블 생성·변경(`ensure_*`)
- 샘플 투자자·봇 계정 시드
- APScheduler 백그라운드 스케줄러 시작

그 결과 세 가지 문제가 있었다.

1. **테스트 불가**: 앱을 import하려면 DB가 필요했다. 닫힌 포트를 DB로 지정하면 import 단계에서 `Connection refused`로 종료된다(검증 기록 참조). 그래서 기존 실습 테스트는 블루프린트 하나만 붙인 별도 Flask 앱을 만들어 우회했다.
2. **확장 불가**: gunicorn worker마다 import가 일어나므로 worker 수만큼 스케줄러와 시드가 중복 실행된다. Dockerfile 주석은 이 때문에 worker를 1개로 제한했다.
3. **공개 배포 부적합**: `SECRET_KEY`가 없으면 조용히 개발용 값으로 기동했다.

## 결정

- **`create_app(settings)`**: 앱을 만들고, 블루프린트·요청 훅·CLI만 등록한다. DB 접속이나 스레드 생성은 하지 않는다.
  - 앱에 직접 붙어 있던 14개 라우트는 `core` 블루프린트로 옮겼다. 규칙·메서드는 같고 엔드포인트 이름에 `core.` 접두사가 붙는다.
  - gunicorn은 Flask 공식 문서의 팩토리 호출 형식 `'app:create_app()'`으로 실행한다.
- **`settings.py`**: 설정은 `APP_PROFILE=local|public`에 따라 달라진다.
  - `local`은 교육용 기본값을 허용한다.
  - `public`은 기본 `SECRET_KEY`·짧은 키·기본 DB 비밀번호일 때 기동을 거부한다. `.env.example`의 자리표시자(`change-me` 등)도 거부한다. 예시 파일을 그대로 복사하면 저장소에 공개된 키로 서명하게 되기 때문이다.
  - `.env` 로드도 이 모듈이 맡는다. 이 모듈은 import 시점에 환경을 읽는 다른 모듈을 import하지 않는다.
- **`bootstrap.py` + Flask CLI**: `flask --app app init-db`, `flask --app app seed-demo`. Flask 문서의 `app.cli.add_command` 방식이다. 기존 함수는 모두 멱등이라 그대로 호출한다.
- **Compose**
  - 일회성 `init` 서비스가 두 명령을 실행하고 종료한다.
  - `python-backend`와 `worker`는 `depends_on: condition: service_completed_successfully`로 그 뒤에 시작한다(Compose 문서).
  - 외부 DB를 쓰는 구성을 위해 `init`의 MariaDB 의존에는 `required: false`(Compose 2.20.0+)를 둔다.
- **`worker.py`**: `scheduler.build_scheduler()`에 `BlockingScheduler`를 넘겨 주기 작업만 실행하는 별도 프로세스다.
- **직접 실행 유지**: `python app.py`는 예전처럼 한 프로세스에서 테이블·시드·스케줄러·개발 서버를 실행한다.

## 결과

- 테스트가 실제 앱 팩토리로 앱을 만든다. DB 없이 import·생성되는지는 별도 프로세스 테스트로 고정했다(`tests/unit/test_app_factory.py`).
- 라우트 표는 스냅샷(`tests/unit/snapshots/routes_local.txt`)으로 고정했다. 원본과 비교한 결과 122개 규칙이 같았다.
- 스케줄러가 웹 프로세스 밖으로 나가서, worker 수를 늘릴 때 남는 장애물은 프로세스 메모리의 제한기·토큰 캐시뿐이다. 이들을 Redis로 옮기는 일은 Phase 1·5에서 한다.
- 오류 로그(`system_error_log.request_meta.endpoint`)에 기록되는 엔드포인트 이름이 14개 라우트에서 `core.*`로 바뀐다.
- `docker compose up`을 다시 실행하면 `init`도 다시 돈다. 멱등이라 데이터는 바뀌지 않는다(검증 기록: 세 번 실행 후 회원 수 52 유지).

## 대안

- **모듈 수준 `app = create_app()` 유지 + import 시 부작용만 제거**: Flask CLI가 앱을 찾기 쉽지만, import마다 앱이 하나 더 만들어진다. 팩토리 호출 방식이 문서의 기본 예라 택하지 않았다.
- **백엔드 컨테이너 시작 명령에서 `init-db`를 실행한 뒤 gunicorn 실행**: 서비스는 하나로 끝나지만, worker가 테이블 준비를 기다릴 방법이 헬스체크에 의존하게 된다. 초기화 단계가 명시적으로 보이는 일회성 서비스를 택했다.

## 근거 (조회일 2026-09-24)

- Flask Gunicorn 배포: `gunicorn -w 4 'hello:create_app()'` — https://flask.palletsprojects.com/en/stable/deploying/gunicorn/
- Flask CLI 명령 등록·앱 팩토리 튜토리얼 — https://flask.palletsprojects.com/en/stable/cli/ , https://flask.palletsprojects.com/en/stable/tutorial/database/
- Flask 테스트 fixture 패턴 — https://flask.palletsprojects.com/en/stable/testing/
- Compose `depends_on` long syntax(`service_completed_successfully`, `required`) — https://docs.docker.com/reference/compose-file/services/
