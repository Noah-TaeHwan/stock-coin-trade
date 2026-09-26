"""비밀번호 정책과 해시(NIST SP 800-63B-4 §3.1.1.2, 2026-09-26 원문 확인).

- NFKC 정규화 후 15~64자, 조합 규칙 없음, 흔한·유출 비밀번호 목록과 전체 일치 거절.
- 저장 형식 "s2$" + bcrypt(base64(sha256(NFKC(비밀번호)))): bcrypt의 72바이트 한계로 뒷부분이 잘리지 않는다.
- 옛 형식($2b$…)은 그대로 검증하고, 로그인에 성공하면 새 형식으로 다시 저장한다(needs_rehash).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import unicodedata
from pathlib import Path

import bcrypt

MIN_LENGTH, MAX_LENGTH = 15, 64
PREFIX = "s2$"
SERVICE_WORDS = ("stockdesk", "tradingdesk")
# 출처·가공 방법: data/COMMON-PASSWORDS-NOTICE.md
BLOCKLIST = Path(__file__).with_name("data") / "common-passwords-15plus.txt"


def normalize(password: str) -> str:
    """입력 방식 차이(전각·조합형)를 없앤다.

    @param password 원문
    @returns NFKC 정규화 문자열
    """
    return unicodedata.normalize("NFKC", password)


@functools.lru_cache(maxsize=1)
def _blocklist() -> frozenset[str]:
    """차단 목록(소문자). 처음 쓸 때 한 번 읽는다.

    @returns 차단할 비밀번호 집합
    """
    return frozenset(line.strip() for line in BLOCKLIST.read_text(encoding="utf-8").splitlines() if line.strip())


def problem(password: str, *, email: str = "", nickname: str = "") -> str | None:
    """정책 위반이면 사용자에게 보여 줄 한국어 메시지, 통과면 None.

    @param password 새 비밀번호
    @param email 가입 이메일
    @param nickname 닉네임
    @returns 위반 메시지 또는 None
    """
    value = normalize(password)
    if len(value) < MIN_LENGTH:
        return f"비밀번호는 {MIN_LENGTH}자 이상이어야 합니다. 문장처럼 길게 만들어 보세요."
    if len(value) > MAX_LENGTH:
        return f"비밀번호는 {MAX_LENGTH}자 이하여야 합니다."
    lowered = value.lower()
    if len(set(lowered)) == 1:
        return "같은 글자만 반복한 비밀번호는 쓸 수 없습니다."
    if lowered in _blocklist():
        return "널리 알려진 비밀번호라 쓸 수 없습니다."
    for word in (email.split("@", 1)[0].lower(), normalize(nickname).lower(), *SERVICE_WORDS):
        if len(word) >= 3 and word in lowered:
            return "이메일·닉네임·서비스 이름이 들어간 비밀번호는 쓸 수 없습니다."
    return None


def _prehash(password: str) -> bytes:
    """bcrypt 입력을 44바이트로 고정한다(잘림 방지).

    @param password 비밀번호 원문
    @returns base64(sha256(NFKC)) 바이트
    """
    return base64.b64encode(hashlib.sha256(normalize(password).encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """저장용 해시.

    @param password 새 비밀번호
    @returns "s2$..." 문자열
    """
    return PREFIX + bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify(password: str, stored: str | None) -> bool:
    """저장된 해시와 비교한다. bcrypt가 아닌 값(UNUSABLE_PASSWORD 등)은 항상 False.

    @param password 입력 비밀번호
    @param stored 저장된 해시
    @returns 일치 여부
    """
    if not stored:
        return False
    try:
        if stored.startswith(PREFIX):
            return bcrypt.checkpw(_prehash(password), stored[len(PREFIX) :].encode("ascii"))
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return False


def needs_rehash(stored: str | None) -> bool:
    """옛 bcrypt 형식이면 True.

    @param stored 저장된 해시
    @returns 새 형식으로 바꿔야 하는지
    """
    return bool(stored) and stored.startswith("$2")


@functools.lru_cache(maxsize=1)
def dummy_hash() -> str:
    """없는 계정도 bcrypt를 한 번 돌려 응답 시간을 맞추는 데 쓰는 해시.

    @returns 새 형식 해시
    """
    return hash_password("timing-equaliser-not-a-real-password")
