"""Flask extensions shared by blueprints and bound in create_app()."""

import ipaddress

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def client_key() -> str:
    """IP 기준 제한 키. IPv6는 /64로 묶어 주소를 바꿔 가며 우회하지 못하게 한다.

    @returns 제한 키(IPv4 주소 또는 IPv6 /64 대역)
    """
    address = get_remote_address()
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 6 and ip.ipv4_mapped:
        # ::ffff:1.2.3.4는 IPv4 사용자다. /64로 묶으면 모든 IPv4가 한 버킷이 된다.
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else address


# Storage and the on/off switch come from app.config (RATELIMIT_STORAGE_URI,
# RATELIMIT_ENABLED), set by Settings.flask_config().
limiter = Limiter(key_func=client_key)
