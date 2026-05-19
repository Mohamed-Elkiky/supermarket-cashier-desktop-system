from django.db import models
from django.conf import settings


class Staff(models.Model):
    ROLE_CHOICES = [
        ('cashier',            'Cashier'),
        ('department_manager', 'Department Manager'),
        ('store_manager',      'Store Manager'),
        ('admin',              'Admin'),
        ('owner',              'Owner'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profile',
        null=True,
        blank=True,
    )
    first_name       = models.CharField(max_length=100)
    last_name        = models.CharField(max_length=100)
    email            = models.EmailField(unique=True)
    phone            = models.CharField(max_length=30, blank=True)
    role             = models.CharField(max_length=30, choices=ROLE_CHOICES, default='cashier')
    department       = models.ForeignKey(
        'departments.Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    commission_rate  = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    hourly_wage      = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active        = models.BooleanField(default=True)
    hired_at         = models.DateField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'staff'

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.role})'