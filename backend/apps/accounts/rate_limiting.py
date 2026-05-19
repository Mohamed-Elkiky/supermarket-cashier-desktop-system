import logging
from django.core.cache import cache

logger = logging.getLogger('apps.accounts')

# Rate limiting config
IP_RATE_LIMIT         = 20    # max login attempts per IP per window
USER_RATE_LIMIT       = 5     # max failed attempts per user before lockout
RATE_WINDOW_SECONDS   = 60    # sliding window in seconds
LOCKOUT_SECONDS       = 900   # 15 minutes lockout


def _ip_attempts_key(ip: str) -> str:
    return f'auth:ip_attempts:{ip}'


def _user_attempts_key(email: str) -> str:
    return f'auth:user_attempts:{email}'


def _user_locked_key(email: str) -> str:
    return f'auth:user_locked:{email}'


def is_ip_rate_limited(ip: str) -> bool:
    key = _ip_attempts_key(ip)
    attempts = cache.get(key, 0)
    return attempts >= IP_RATE_LIMIT


def is_user_locked(email: str) -> bool:
    return bool(cache.get(_user_locked_key(email)))


def record_failed_attempt(ip: str, email: str):
    # Increment IP attempts
    ip_key = _ip_attempts_key(ip)
    ip_attempts = cache.get(ip_key, 0) + 1
    cache.set(ip_key, ip_attempts, timeout=RATE_WINDOW_SECONDS)

    # Increment user attempts
    user_key = _user_attempts_key(email)
    user_attempts = cache.get(user_key, 0) + 1
    cache.set(user_key, user_attempts, timeout=RATE_WINDOW_SECONDS)

    # Lock account after threshold
    if user_attempts >= USER_RATE_LIMIT:
        cache.set(_user_locked_key(email), True, timeout=LOCKOUT_SECONDS)
        logger.warning(
            'Account locked after %d failed attempts: %s from IP %s',
            user_attempts, email, ip,
        )


def clear_failed_attempts(ip: str, email: str):
    cache.delete(_ip_attempts_key(ip))
    cache.delete(_user_attempts_key(email))
    cache.delete(_user_locked_key(email))


def get_lockout_remaining(email: str) -> int:
    ttl = cache.ttl(_user_locked_key(email))
    return max(ttl, 0)