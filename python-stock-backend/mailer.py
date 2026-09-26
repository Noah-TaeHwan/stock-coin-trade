"""회원 메일(인증·가입 안내·재설정). 표준 라이브러리 smtplib만 쓴다(설계: S1 스펙 ⑤).

- 제목·본문은 코드에 고정한 템플릿이고 닉네임 같은 사용자 입력을 넣지 않는다(피싱 문구 주입 차단).
- 링크는 PUBLIC_BASE_URL로만 만들고 토큰은 프래그먼트(#t=)에 둔다(서버·접근 로그·Referer에 남지 않게).
- 발송은 요청 밖 스레드에서 하고 실패는 응답에 드러내지 않는다. 로그에는 요청 ID·종류·오류 이름만 남긴다.
"""

from __future__ import annotations

import hashlib
import logging
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app
from limits import parse

from errors import request_id
from extensions import limiter

log = logging.getLogger("mailer")

GLOBAL_DAILY = parse("200/day")
PER_ADDRESS = (parse("3/hour"), parse("10/day"))
MAX_ADDRESS_LENGTH = 254
# 주소 하나만: 공백·쉼표·세미콜론·꺾쇠·줄바꿈·두 번째 @가 없어야 한다.
_SINGLE_ADDRESS = re.compile(r"[^\s,;<>@]+@[^\s,;<>@]+\.[^\s,;<>@]+")
TEMPLATES = {
    "verify": (
        "[Noah Trading Desk] 이메일 주소를 확인해 주세요",
        "아래 링크를 열면 가입이 끝납니다. 링크는 24시간 동안 한 번만 쓸 수 있습니다.\n\n{link}\n\n"
        "가입한 적이 없다면 이 메일을 무시하세요.",
    ),
    "exists": (
        "[Noah Trading Desk] 이미 가입된 주소입니다",
        "이 주소로 가입 요청이 있었지만 이미 가입된 주소입니다. 비밀번호가 기억나지 않으면 아래에서 재설정하세요.\n\n"
        "{link}\n\n요청한 적이 없다면 이 메일을 무시하세요.",
    ),
    "reset": (
        "[Noah Trading Desk] 비밀번호 재설정",
        "아래 링크에서 새 비밀번호를 정하세요. 링크는 30분 동안 한 번만 쓸 수 있습니다.\n\n{link}\n\n"
        "요청한 적이 없다면 이 메일을 무시하세요. 비밀번호는 바뀌지 않습니다.",
    ),
}
PATHS = {
    "verify": "/member/verify.html#t={token}",
    "exists": "/member/reset-request.html",
    "reset": "/member/reset.html#t={token}",
}


def valid_address(address: str) -> bool:
    """주소 하나짜리 이메일인지.

    @param address 받는 주소
    @returns 발송해도 되는 단일 주소면 True
    """
    return len(address) <= MAX_ADDRESS_LENGTH and bool(_SINGLE_ADDRESS.fullmatch(address))


def build(kind: str, to_addr: str, token: str | None, *, sender: str, base_url: str) -> EmailMessage:
    """고정 템플릿으로 메일을 만든다.

    @param kind "verify"·"exists"·"reset"
    @param to_addr 받는 주소(단일)
    @param token 링크에 넣을 1회용 토큰(없으면 빈 값)
    @param sender 보내는 주소(SMTP_FROM)
    @param base_url 링크 기준 주소(PUBLIC_BASE_URL)
    @returns 보낼 메시지
    """
    if not valid_address(to_addr):
        raise ValueError("mail recipient must be a single address")
    subject, body = TEMPLATES[kind]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to_addr
    msg.set_content(body.format(link=base_url + PATHS[kind].format(token=token or "")))
    return msg


def send(msg: EmailMessage, config: dict) -> None:
    """SMTP로 한 통 보낸다. 받는 주소는 msg["To"] 하나로 고정한다.

    @param msg build가 만든 메시지
    @param config SMTP_HOST·SMTP_PORT·SMTP_USER·SMTP_PASSWORD·SMTP_STARTTLS
    """
    with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=15) as smtp:
        if config["SMTP_STARTTLS"]:
            smtp.starttls(context=ssl.create_default_context())
        if config["SMTP_USER"]:
            smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        smtp.send_message(msg, to_addrs=[msg["To"]])


def _within_caps(address: str) -> bool:
    """전역 하루·수신 주소별 상한 안이면 한 통을 센다. limiter가 꺼진 배포(local)는 세지 않는다.

    @param address 받는 주소
    @returns 보내도 되면 True
    """
    if not limiter.enabled:
        return True
    strategy = limiter.limiter  # public은 Redis 공유 저장소
    key = hashlib.sha256(address.lower().encode("utf-8")).hexdigest()
    checks = [(GLOBAL_DAILY, ("mail", "all")), *((limit, ("mail", key)) for limit in PER_ADDRESS)]
    if not all(strategy.test(limit, *keys) for limit, keys in checks):
        return False
    for limit, keys in checks:
        strategy.hit(limit, *keys)
    return True


def queue(kind: str, to_addr: str, token: str | None = None) -> None:
    """메일을 백그라운드로 보낸다. 메일 미설정·잘못된 주소·상한 초과면 조용히 건너뛴다.

    @param kind "verify"·"exists"·"reset"
    @param to_addr 받는 주소
    @param token 링크 토큰
    """
    config = current_app.config
    if not config.get("SMTP_HOST") or not valid_address(to_addr):
        return
    rid = request_id()
    if not _within_caps(to_addr):
        log.warning("mail cap reached request_id=%s kind=%s", rid, kind)
        return
    msg = build(kind, to_addr, token, sender=config["SMTP_FROM"], base_url=config["PUBLIC_BASE_URL"])
    snapshot = {key: config[key] for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_STARTTLS")}

    def run() -> None:
        try:
            send(msg, snapshot)
        except Exception as exc:  # noqa: BLE001 - 발송 실패는 요청에 드러내지 않는다
            log.warning("mail send failed request_id=%s kind=%s error=%s", rid, kind, type(exc).__name__)

    threading.Thread(target=run, daemon=True).start()
