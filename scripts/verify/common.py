"""검증 스크립트 공용 도구: HTTP 호출, 증거 기록(비밀 가림), DB 조회, 종료 코드.

표준 라이브러리만 쓴다. 대상은 전용 스택 stockdesk-verify(기본 http://127.0.0.1:3334)다.
"""

from __future__ import annotations

import copy
import http.cookiejar
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from collections.abc import Callable
from typing import Any
from datetime import datetime, timezone
from pathlib import Path

PASS, FAIL, UNMET = 0, 1, 2
PROJECT = "stockdesk-verify"
VERIFY_NETLOC = "127.0.0.1:3334"
# 경로만 바꿔 전제 불충족을 시험할 때 쓴다. 호스트·포트가 검증 스택이 아니면 run()이 주행을 거부한다.
BASE_URL = os.environ.get("VERIFY_BASE_URL", f"http://{VERIFY_NETLOC}")
ARTIFACTS = Path(os.environ.get("VERIFY_ARTIFACTS", ".verify-artifacts"))
_SECRET_KEY = re.compile(r"(?i)(token|password|secret|cookie|sid|csrf)")
# 자유 문장(예외 메시지 등) 속 "키: 값", "키=값"의 값. 앞이 영문자면 다른 단어의 일부(inside 등)로 본다.
_SECRET_IN_TEXT = re.compile(r"(?i)((?<![A-Za-z])(?:token|password|secret|cookie|sid|csrf)\w*['\"]?\s*[:=]\s*['\"]?)([^'\",}\s&]+)")


def redact(value):
    """dict·list 안에서 비밀로 보이는 키의 값을 '***'로 바꾼 사본을 돌려준다.

    @param value 요청·응답 본문(dict, list, 스칼라)
    @returns 비밀 값을 가린 사본
    """
    if isinstance(value, dict):
        return {key: ("***" if _SECRET_KEY.search(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_IN_TEXT.sub(r"\1***", value)
    return value


def unique_email(prefix: str = "verify") -> str:
    """실행마다 겹치지 않는 예약 도메인(.test) 이메일을 만든다.

    @param prefix 주소 앞부분
    @returns 예: verify-1790000000-a1b2c3@example.test
    """
    return f"{prefix}-{int(time.time())}-{secrets.token_hex(3)}@example.test"


class Recorder:
    """한 기능 주행의 요청·응답을 증거 폴더의 transcript.json으로 남긴다."""

    def __init__(self, feature_id: str, root: Path = ARTIFACTS):
        """@param feature_id 기능 ID(F1 등) @param root 증거 최상위 폴더"""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # 같은 초에 여러 번 실행해도 증거가 덮이지 않게 무작위 네 글자를 붙인다.
        self.dir = Path(root) / f"{stamp}-{secrets.token_hex(2)}-{feature_id}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []

    def add(self, step: str, request: dict, status: int, body) -> None:
        """한 단계를 기록한다. @param step 단계 이름 @param request 보낸 값 @param status HTTP 상태 @param body 응답 본문"""
        self.steps.append({"step": step, "request": redact(request), "status": status, "body": redact(body)})

    def finish(self, verdict: str) -> Path:
        """판정과 함께 파일로 쓴다. @param verdict PASS·FAIL·UNMET @returns transcript.json 경로"""
        path = self.dir / "transcript.json"
        path.write_text(json.dumps({"verdict": verdict, "steps": self.steps}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path


def _json(raw: bytes):
    """응답 바이트를 JSON으로, 실패하면 앞부분 문자열로 돌려준다."""
    try:
        return json.loads(raw.decode("utf-8") or "null")
    except ValueError:
        return raw[:200].decode("utf-8", "replace")


class Client:
    """쿠키를 유지하는 최소 HTTP 클라이언트."""

    def __init__(self, base: str | None = None):
        """@param base 대상 기본 URL(기본: BASE_URL)"""
        self.base = base or BASE_URL
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))

    def clone(self) -> Client:
        """같은 쿠키를 가진 새 클라이언트(복사된 쿠키 재사용 시험용).

        @returns 쿠키를 복사한 새 Client
        """
        twin = Client(self.base)
        for cookie in self._jar:
            twin._jar.set_cookie(copy.copy(cookie))
        return twin

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        """요청을 보내고 (상태, JSON 본문)을 돌려준다. @param method HTTP 메서드 @param path 경로 @param body JSON 본문"""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=30) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _json(exc.read())


def mariadb_scalar(sql: str) -> str:
    """검증 스택 MariaDB에서 한 값을 조회한다. 비밀번호는 컨테이너 환경변수로만 쓴다.

    @param sql 우리가 만든 값만 넣은 SELECT 문(외부 입력 금지)
    @returns 첫 행 첫 열 문자열
    """
    container = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}",
         "--filter", "label=com.docker.compose.service=mariadb"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not container:
        raise RuntimeError(f"{PROJECT} mariadb 컨테이너가 없습니다")
    script = 'MYSQL_PWD="$MARIADB_PASSWORD" mariadb -u"$MARIADB_USER" mockinv -N -e "$0"'
    return subprocess.run(["docker", "exec", container, "sh", "-c", script, sql],
                          check=True, capture_output=True, text=True).stdout.strip()


def run(feature_id: str, steps: Callable[[Client, Recorder], None], root: Path = ARTIFACTS) -> int:
    """기능 주행을 실행하고 판정·증거 경로를 출력한다.

    @param feature_id 기능 ID
    @param steps (client, recorder)를 받아 실패 시 AssertionError, 전제 불충족 시 ConnectionError를 낸다
    @param root 증거 최상위 폴더
    @returns 종료 코드(PASS·FAIL·UNMET)
    """
    recorder, client = Recorder(feature_id, root), Client()
    try:
        if urlparse(client.base).netloc != VERIFY_NETLOC:
            raise ConnectionError(f"검증 스택({VERIFY_NETLOC})이 아닌 곳은 주행하지 않습니다: {client.base}")
        steps(client, recorder)
        verdict, code = "PASS", PASS
    except AssertionError as exc:
        recorder.add("assertion", {}, 0, str(exc))
        verdict, code = "FAIL", FAIL
    except (ConnectionError, urllib.error.URLError, RuntimeError) as exc:
        recorder.add("precondition", {}, 0, str(exc))
        verdict, code = "UNMET", UNMET
    except Exception as exc:  # noqa: BLE001 — 예상 밖 응답 형식 등도 증거를 남기고 실패로 판정한다
        recorder.add("unexpected", {}, 0, f"{type(exc).__name__}: {exc}")
        verdict, code = "FAIL", FAIL
    path = recorder.finish(verdict)
    print(f"{feature_id}: {verdict} evidence={path}")
    return code
