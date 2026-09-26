# 태그를 버전까지 고정한다(2026-09-25 기준 python:3.11-slim과 같은 3.11.16, Debian trixie).
FROM python:3.11.16-slim-trixie
WORKDIR /app

# gunicorn을 root로 돌리지 않는다(Flask 배포 문서). 로컬 LEAN 실습처럼 호스트
# docker.sock이 필요한 구성은 Compose의 group_add로 소켓 그룹을 준다.
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

# AI Sheet의 LEAN 백테스트 버튼이 호스트 Docker 데몬에 `docker` CLI로 직접
# 명령을 보낸다(Docker-outside-of-Docker). 데몬은 필요 없고 클라이언트만
# 필요하므로 docker-cli만 설치한다(docker.io는 불필요한 dockerd까지 끌고 온다).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt는 직접 의존성, requirements.lock은 uv로 만든 전이 의존성까지의
# 고정 버전·해시다. 해시 검사 모드라 lock에 없는 패키지나 다른 파일은 설치하지 않는다.
COPY python-stock-backend/requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# 임베딩 모델(qdrant_service.EMBED_MODEL)을 빌드 때 받아 두어, 실행 중에는 네트워크 없이 뜬다.
# 캐시 경로를 고정해 비루트 사용자도 읽을 수 있게 한다.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python3 -c "\
from fastembed import TextEmbedding; \
list(TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2').embed(['warmup'])); \
print('fastembed model ready')" \
    && chown -R app:app /opt/fastembed

COPY python-stock-backend/*.py .
# KIS API 탐색기 카탈로그(공식 예제에서 생성한 JSON)
COPY python-stock-backend/kis_api_catalog.json .
# 흔한 비밀번호 차단 목록(passwords.py가 ./data에서 읽는다)
COPY python-stock-backend/data/ ./data/
# Noah가 새로 쓴 패키지(src/)와 데이터 소스 레지스트리(config/). marketdata.registry는
# /app/src/marketdata 기준 두 단계 위의 config/data_sources.toml을 읽는다.
COPY src/ ./src/
COPY config/ ./config/
ENV PYTHONPATH=/app/src
# 백테스트 영수증(quantlab.receipts)에 남길 커밋. 이미지에는 .git이 없으므로 빌드 인자로 받는다.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

USER app

EXPOSE 8200
# KIS 토큰·호출 제한은 프로세스 메모리에서 공유하므로 worker는 1개로 두고
# 요청 동시성은 threads로 처리한다. 다중 worker 확장은 Redis 기반 제한기로
# 전환한 뒤 적용해야 한다.
# 테이블·시드는 `flask --app app init-db`/`seed-demo`(Compose의 init 서비스),
# 주기 작업은 `python worker.py`(Compose의 worker 서비스)가 맡는다.
CMD ["gunicorn", "--bind", "0.0.0.0:8200", "--workers", "1", "--threads", "8", "--timeout", "120", "app:create_app()"]
