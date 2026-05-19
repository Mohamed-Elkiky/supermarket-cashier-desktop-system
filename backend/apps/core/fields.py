from django.db import models
from .encryption import encrypt, decrypt


class EncryptedField(models.TextField):
    """
    A transparent encrypted text field.
    Values are encrypted before saving and decrypted on access.
    Never stores plaintext in the database.
    """

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt(value)

    def to_python(self, value):
        if value is None:
            return value
        return value

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt(value)