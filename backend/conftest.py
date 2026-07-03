"""
Sandbox-only test compatibility shims.

This environment has no reachable Postgres or Vault server (only SQLite via
DATABASE_URL for local test runs). Production always runs against real
Postgres + Vault; these shims activate only when those aren't available and
never touch the actual model/field/encryption implementation.
"""
import json
import time

import pytest
from cryptography.fernet import Fernet
from django.db import connection

import apps.accounts.views as _accounts_views_module
import apps.core.encryption as _encryption_module
import apps.core.mixins as _mixins_module


def _use_local_memory_cache_if_redis_unreachable():
    """
    CACHES points at a Redis instance only reachable inside the project's
    docker-compose network (hostname 'redis') — unreachable in this sandbox.
    Swap to Django's in-process LocMemCache for the test session instead, so
    apps.accounts.rate_limiting (pure django.core.cache usage — login
    lockout, IP rate limiting) is actually exercisable. No-op if Redis is
    genuinely reachable (e.g. a real dev/CI environment).

    LocMemCache has no .ttl() — django-redis adds that as a Redis-specific
    extension that apps.accounts.rate_limiting.get_lockout_remaining()
    depends on. Patch one on, backed by LocMemCache's own _expire_info
    bookkeeping, matching django-redis's ttl() contract: 0 if the key is
    missing/expired, None if it has no expiry, else seconds remaining.
    """
    import redis
    from django.conf import settings as django_settings

    redis_location = django_settings.CACHES["default"]["LOCATION"]
    try:
        redis.Redis.from_url(redis_location, socket_connect_timeout=1).ping()
        return
    except Exception:
        pass

    django_settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-cache",
        }
    }

    from django.core.cache.backends.locmem import LocMemCache

    def ttl(self, key, version=None):
        full_key = self.make_key(key, version=version)
        exp = self._expire_info.get(full_key, 0)
        if exp == 0:
            return 0
        if exp is None:
            return None
        return max(0, int(exp - time.time()))

    LocMemCache.ttl = ttl


_use_local_memory_cache_if_redis_unreachable()


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """LocMemCache is one process-wide dict — without this, rate-limit/lockout
    counters from one test would leak into the next (unlike the DB, which
    pytest-django rolls back per test automatically)."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _bypass_vault_for_encryption(monkeypatch):
    """
    apps.core.encryption fetches its Fernet key from Vault on first use.
    Vault isn't reachable here, so tests touching apps.core.fields.EncryptedField
    (e.g. apps.loyalty.models.Customer's PII fields) would fail before ever
    reaching application logic. Inject a locally-generated, ephemeral Fernet
    key instead — scoped to this test process only.
    """
    monkeypatch.setattr(_encryption_module, "_fernet_instance", Fernet(Fernet.generate_key()))


def _sqlite_compatible_log_activity(request, action, entity_type, entity_id,
                                    before_state=None, after_state=None):
    """Mirrors apps.core.activity.log_activity() without the ::jsonb casts."""
    import logging
    from django.utils import timezone

    logger = logging.getLogger("apps.core")
    try:
        actor_id = None
        actor_role = None
        if request and hasattr(request, "user") and request.user.is_authenticated:
            actor_id = request.user.id
            if hasattr(request.user, "staff_profile") and request.user.staff_profile:
                actor_role = request.user.staff_profile.role

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO activity_log (
                    actor_staff_id, actor_role, action, entity_type, entity_id,
                    before_state, after_state, device_identifier, ip_address, occurred_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    actor_id, actor_role, action, entity_type, str(entity_id),
                    json.dumps(before_state) if before_state is not None else None,
                    json.dumps(after_state) if after_state is not None else None,
                    None, None, timezone.now(),
                ],
            )
    except Exception as e:
        logger.error("Failed to write activity log (sqlite test shim): %s", str(e))


@pytest.fixture(autouse=True)
def _bypass_jsonb_cast_for_sqlite(monkeypatch):
    """
    apps.core.activity.log_activity() casts before_state/after_state with the
    Postgres-only `%s::jsonb` syntax, which is invalid SQL under SQLite —
    every call silently fails (caught by log_activity's own broad
    except-and-log) and no row is ever written. Both apps.core.mixins
    (ActivityLogMixin.log(), used by most apps) and apps.accounts.views
    (LoginView/LogoutView, which call log_activity directly instead of using
    the mixin) import the name at module load time
    (`from .activity import log_activity` / `from apps.core.activity import
    log_activity`), so each needs patching at its own binding.
    """
    if connection.vendor == "postgresql":
        return
    monkeypatch.setattr(_mixins_module, "log_activity", _sqlite_compatible_log_activity)
    monkeypatch.setattr(_accounts_views_module, "log_activity", _sqlite_compatible_log_activity)


def _patch_array_field_for_sqlite():
    """
    django.contrib.postgres.fields.ArrayField (apps.loyalty.models.Customer.
    allergen_preferences) relies on psycopg's native array wire format and a
    Postgres-only `::type[]` cast placeholder — it cannot run against SQLite
    at all. Round-trip it through JSON instead, for local verification only.
    Must run at import time (before pytest-django applies migrations), and is
    a no-op when DATABASE_URL actually points at Postgres.
    """
    if connection.vendor == "postgresql":
        return

    from apps.loyalty.models import Customer

    field = Customer._meta.get_field("allergen_preferences")

    def get_db_prep_value(value, connection, prepared=False):
        if isinstance(value, (list, tuple)):
            return json.dumps(list(value))
        return value

    def from_db_value(value, expression, connection):
        if value is None:
            return []
        if isinstance(value, str):
            return json.loads(value)
        return value

    def get_placeholder(value, compiler, connection):
        return "%s"

    def db_type(connection):
        return "text"

    field.get_db_prep_value = get_db_prep_value
    field.from_db_value = from_db_value
    field.get_placeholder = get_placeholder
    field.db_type = db_type


_patch_array_field_for_sqlite()
