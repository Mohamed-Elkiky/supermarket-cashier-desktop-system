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
