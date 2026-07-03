# Vault is unreachable in this sandbox — apps.core.encryption.get_fernet()
# is patched (backend/conftest.py, autouse) to use a locally-generated,
# ephemeral Fernet key for the whole test session instead of fetching one
# from Vault. Production always fetches the real key from Vault; these tests
# exercise the encryption/rotation logic itself, independent of the source
# of the key.
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet, InvalidToken

import pytest

import apps.core.encryption as encryption_module
from .encryption import _get_vault_client, _load_key_from_vault, decrypt, encrypt, get_fernet, rotate_key


class TestEncryptDecryptRoundTrip:
    def test_round_trip_returns_original_plaintext(self):
        plaintext = "Sensitive Customer Data"
        ciphertext = encrypt(plaintext)
        assert ciphertext != plaintext
        assert decrypt(ciphertext) == plaintext

    def test_same_plaintext_encrypted_twice_produces_different_ciphertext(self):
        """
        Fernet ciphertext is non-deterministic (random IV per call) — this is
        exactly the property that ruled out encrypting email/phone in the
        loyalty app (it would break the email UNIQUE constraint and any
        equality lookup), so it's worth asserting explicitly rather than
        just assuming it.
        """
        plaintext = "same-value"
        first = encrypt(plaintext)
        second = encrypt(plaintext)
        assert first != second
        assert decrypt(first) == plaintext
        assert decrypt(second) == plaintext

    def test_encrypt_empty_string_returns_unchanged(self):
        assert encrypt("") == ""

    def test_decrypt_empty_string_returns_unchanged(self):
        assert decrypt("") == ""

    def test_encrypt_none_returns_none(self):
        assert encrypt(None) is None

    def test_decrypt_none_returns_none(self):
        assert decrypt(None) is None


class TestRotateKey:
    def test_reencrypts_values_under_new_key(self):
        old_fernet = get_fernet()
        plaintext_values = ["Alice", "Bob", "123 Main St"]
        old_ciphertexts = [old_fernet.encrypt(v.encode()).decode() for v in plaintext_values]

        new_key = Fernet.generate_key().decode()
        rotated = rotate_key(new_key, old_ciphertexts)

        new_fernet = Fernet(new_key.encode())
        for plaintext, rotated_ciphertext in zip(plaintext_values, rotated):
            assert new_fernet.decrypt(rotated_ciphertext.encode()).decode() == plaintext

    def test_rotated_values_no_longer_decrypt_with_old_key(self):
        old_fernet = get_fernet()
        old_ciphertext = old_fernet.encrypt(b"secret").decode()

        new_key = Fernet.generate_key().decode()
        rotated = rotate_key(new_key, [old_ciphertext])

        with pytest.raises(InvalidToken):
            old_fernet.decrypt(rotated[0].encode())

    def test_empty_list_returns_empty_list(self):
        new_key = Fernet.generate_key().decode()
        assert rotate_key(new_key, []) == []


# ── Vault key loading (mocked — no live Vault in this sandbox) ────────────────
#
# conftest.py's autouse fixture bypasses get_fernet() entirely for every other
# test in the suite (it pre-seeds _fernet_instance), so _get_vault_client()/
# _load_key_from_vault()/get_fernet()'s lazy-load branch are otherwise never
# exercised. Mock hvac.Client directly here instead of hitting real Vault.

class TestVaultKeyLoading:
    def test_get_vault_client_builds_hvac_client_from_settings(self, settings):
        settings.VAULT_ADDR = "http://vault.test:8200"
        settings.VAULT_TOKEN = "test-vault-token"
        with patch("apps.core.encryption.hvac.Client") as mock_client_cls:
            _get_vault_client()
        mock_client_cls.assert_called_once_with(url="http://vault.test:8200", token="test-vault-token")

    def test_load_key_from_vault_returns_usable_fernet(self):
        fake_key = Fernet.generate_key().decode()
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"ENCRYPTION_KEY": fake_key}}
        }
        with patch("apps.core.encryption._get_vault_client", return_value=mock_client):
            fernet = _load_key_from_vault()

        assert isinstance(fernet, Fernet)
        token = fernet.encrypt(b"hello")
        assert fernet.decrypt(token) == b"hello"

    def test_load_key_from_vault_raises_when_not_authenticated(self):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = False
        with patch("apps.core.encryption._get_vault_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Vault authentication failed"):
                _load_key_from_vault()

    def test_get_fernet_lazy_loads_then_caches(self, monkeypatch):
        fake_key = Fernet.generate_key().decode()
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"ENCRYPTION_KEY": fake_key}}
        }
        # Force the lazy-load branch — every other test in this suite runs
        # with _fernet_instance already pre-seeded by conftest.py.
        monkeypatch.setattr(encryption_module, "_fernet_instance", None)

        with patch("apps.core.encryption._get_vault_client", return_value=mock_client) as mock_get_client:
            first = get_fernet()
        assert mock_get_client.call_count == 1

        # Second call must be served from the cache — no further Vault call.
        with patch("apps.core.encryption._get_vault_client") as mock_get_client_again:
            second = get_fernet()
        mock_get_client_again.assert_not_called()
        assert first is second
