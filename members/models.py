from django.contrib.auth.models import AbstractUser
from django.db import models


class Member(AbstractUser):
    """Ein Member ist zugleich Login-Konto und möglicher Verantwortlicher für Crates."""

    oidc_sub = models.CharField(
        'OIDC-Subject', max_length=255, unique=True, null=True, blank=True, editable=False,
        help_text='Unveränderliche Kennung des Kontos beim Identity Provider.',
    )

    class Meta:
        verbose_name = 'Member'
        verbose_name_plural = 'Member'
        ordering = ['username']

    def __str__(self):
        return self.get_full_name() or self.username
