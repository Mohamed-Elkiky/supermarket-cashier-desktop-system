from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.fields import EncryptedField


class Customer(models.Model):
    """Matches the `customers` table in migrations/V004__customers_and_loyalty.sql."""

    # PII — encrypted at rest via apps.core.fields.EncryptedField.
    first_name = EncryptedField()
    last_name = EncryptedField()
    # email/phone stay plaintext: email has a UNIQUE constraint and phone is
    # looked up directly at POS — Fernet ciphertext is non-deterministic, so
    # encrypting either would break DB-level uniqueness and equality lookups.
    email = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    # SQL column is DATE, but EncryptedField is a TextField (Fernet ciphertext
    # is opaque text, not comparable/sortable as a real date at the DB level).
    # Stored as an encrypted ISO-8601 string ("YYYY-MM-DD") and converted back
    # to a date by the service layer — never queried/filtered at the DB level.
    date_of_birth = EncryptedField(null=True, blank=True)
    address_line1 = EncryptedField(null=True, blank=True)
    address_line2 = EncryptedField(null=True, blank=True)
    city = EncryptedField(null=True, blank=True)
    postcode = EncryptedField(null=True, blank=True)
    # Allergen IDs (apps.inventory.models.Allergen) the customer wants
    # flagged for basket-conflict warnings at POS.
    allergen_preferences = ArrayField(
        models.IntegerField(), default=list, blank=True,
    )
    # GDPR consent
    marketing_consent = models.BooleanField(default=False)
    marketing_consent_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customers"
        indexes = [
            models.Index(fields=["email"], name="idx_customers_email"),
            models.Index(fields=["phone"], name="idx_customers_phone"),
            models.Index(fields=["postcode"], name="idx_customers_postcode"),
        ]

    def __str__(self):
        return f"Customer #{self.id}"


class LoyaltyAccount(models.Model):
    """Matches the `loyalty_accounts` table in V004__customers_and_loyalty.sql."""

    class Tier(models.TextChoices):
        BRONZE = "bronze", "Bronze"
        SILVER = "silver", "Silver"
        GOLD = "gold", "Gold"

    customer = models.OneToOneField(
        Customer, on_delete=models.CASCADE, related_name="loyalty_account",
    )
    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.BRONZE)
    # Cumulative lifetime spend in pence — integer avoids float rounding.
    lifetime_spend_pence = models.BigIntegerField(default=0)
    # Cache of SUM(loyalty_transactions.points) — always recalculated on
    # redemption/adjustment to prevent drift (see LoyaltyTransaction).
    points_balance = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "loyalty_accounts"

    def __str__(self):
        return f"LoyaltyAccount #{self.id} ({self.tier}) — customer #{self.customer_id}"


class LoyaltyTransaction(models.Model):
    """
    Immutable loyalty ledger entry — matches `loyalty_transactions` in
    V004__customers_and_loyalty.sql. No row is ever updated or deleted.
    """

    class TransactionType(models.TextChoices):
        EARN = "earn", "Earn"
        REDEEM = "redeem", "Redeem"
        ADJUSTMENT = "adjustment", "Adjustment"
        EXPIRE = "expire", "Expire"

    loyalty_account = models.ForeignKey(
        LoyaltyAccount, on_delete=models.PROTECT, related_name="transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    # Positive = earn, negative = redeem/expire.
    points = models.IntegerField()
    order = models.ForeignKey(
        "pos.Order", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="loyalty_transactions",
    )
    # Mandatory for adjustment type — matches the SQL CHECK constraint
    # `adjustment_requires_reason`.
    reason = models.TextField(null=True, blank=True)
    performed_by = models.ForeignKey(
        "staff.Staff", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="loyalty_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "loyalty_transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["loyalty_account"], name="idx_loyalty_tx_account_id"),
            models.Index(fields=["order"], name="idx_loyalty_tx_order_id"),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.points}pts — account #{self.loyalty_account_id}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.transaction_type == self.TransactionType.ADJUSTMENT and not self.reason:
            raise ValidationError("reason is required for adjustment transactions.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "LoyaltyTransaction entries are immutable. "
                "Create a new entry instead of updating."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "LoyaltyTransaction entries cannot be deleted. "
            "They are permanent loyalty ledger records."
        )
