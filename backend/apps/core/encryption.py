import logging
import hvac
from cryptography.fernet import Fernet
from django.conf import settings

logger = logging.getLogger('apps.core')

# In-memory key cache — fetched once from Vault on first use
_fernet_instance = None


def _get_vault_client():
    return hvac.Client(
        url=settings.VAULT_ADDR,
        token=settings.VAULT_TOKEN,
    )


def _load_key_from_vault() -> Fernet:
    client = _get_vault_client()
    if not client.is_authenticated():
        raise RuntimeError('Vault authentication failed — check VAULT_TOKEN.')

    secret = client.secrets.kv.v2.read_secret_version(
        path='supermarket/encryption',
        mount_point='secret',
    )
    key = secret['data']['data']['ENCRYPTION_KEY']
    logger.info('Encryption key loaded from Vault successfully.')
    return Fernet(key.encode())


def get_fernet() -> Fernet:
    """
    Returns the cached Fernet instance.
    Fetches from Vault on first call only.
    """
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = _load_key_from_vault()
    return _fernet_instance


def encrypt(value: str) -> str:
    """Encrypt a string value. Returns ciphertext as a string."""
    if not value:
        return value
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext."""
    if not value:
        return value
    return get_fernet().decrypt(value.encode()).decode()


def rotate_key(new_key: str, encrypted_values: list[str]) -> list[str]:
    """
    Re-encrypts a list of ciphertext values with a new key.
    Used during key rotation — call this before updating Vault.
    """
    old_fernet = get_fernet()
    new_fernet = Fernet(new_key.encode())
    rotated = []
    for val in encrypted_values:
        plaintext = old_fernet.decrypt(val.encode())
        rotated.append(new_fernet.encrypt(plaintext).decode())
    return rotated