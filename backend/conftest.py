"""
Sandbox-only test compatibility shims.

This environment has no reachable Postgres or Vault server (only SQLite via
DATABASE_URL for local test runs). Production always runs against real
Postgres + Vault; these shims activate only when those aren't available and
never touch the actual model/field/encryption implementation.
"""
import json

import pytest
from cryptography.fernet import Fernet
from django.db import connection

import apps.core.encryption as _encryption_module
import apps.core.mixins as _mixins_module


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
    except-and-log) and no row is ever written. ActivityLogMixin.log() calls
    the name as bound into apps.core.mixins at import time
    (`from .activity import log_activity`), so patch it there.
    """
    if connection.vendor == "postgresql":
        return
    monkeypatch.setattr(_mixins_module, "log_activity", _sqlite_compatible_log_activity)


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
