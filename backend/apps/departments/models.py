from django.db import models


class Department(models.Model):
    name         = models.CharField(max_length=100, unique=True)
    slug         = models.SlugField(max_length=100, unique=True)
    tax_rate     = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    is_active    = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'departments'

    def __str__(self):
        return self.name