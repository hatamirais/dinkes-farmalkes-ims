"""
Trusted client IP resolution for security logging.

Forwarded IP headers are only accepted from explicitly configured reverse
proxies. Direct requests and untrusted peers fall back to REMOTE_ADDR.
"""

from ipaddress import ip_address, ip_network

from django.conf import settings


def _parse_ip(value):
    try:
        return ip_address(str(value).strip())
    except ValueError:
        return None


def _trusted_proxy_networks():
    for configured_proxy in getattr(settings, "AUTH_AUDIT_TRUSTED_PROXIES", ()):
        configured_proxy = str(configured_proxy).strip()
        if not configured_proxy:
            continue
        try:
            yield ip_network(configured_proxy, strict=False)
        except ValueError:
            continue


def _is_trusted_proxy(remote_addr):
    remote_ip = _parse_ip(remote_addr)
    if remote_ip is None:
        return False
    return any(remote_ip in network for network in _trusted_proxy_networks())


def _forwarded_for_chain(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    chain = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
    parsed_chain = [_parse_ip(entry) for entry in chain]
    if not parsed_chain or any(parsed_ip is None for parsed_ip in parsed_chain):
        return []
    return [str(parsed_ip) for parsed_ip in parsed_chain]


def get_client_ip(request):
    """
    Resolve the client IP for audit logs without trusting spoofable headers.

    X-Forwarded-For is accepted only when REMOTE_ADDR is an explicitly trusted
    proxy and the forwarded chain is syntactically valid.
    """
    remote_addr = request.META.get("REMOTE_ADDR", "")
    remote_ip = _parse_ip(remote_addr)
    if remote_ip is None:
        return "unknown"

    if _is_trusted_proxy(remote_addr):
        forwarded_chain = _forwarded_for_chain(request)
        if forwarded_chain:
            return forwarded_chain[0]

    return str(remote_ip)
