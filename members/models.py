from django.contrib.auth.models import AbstractUser
from django.db import models


class Member(AbstractUser):
    """Ein Member ist zugleich Login-Konto und möglicher Verantwortlicher für Crates."""

    # Platzhalter für Crates, deren Verantwortliche niemand kennt. Kein echtes
    # Konto: inaktiv und ohne Passwort, angelegt per Migration.
    UNKNOWN_USERNAME = 'unbecannt'

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

    @classmethod
    def unknown(cls):
        """Der Platzhalter „unbecannt“."""
        member, created = cls.objects.get_or_create(username=cls.UNKNOWN_USERNAME, defaults={'is_active': False})
        if created:
            member.set_unusable_password()
            member.save(update_fields=['password'])
        return member

    @property
    def is_unknown(self):
        return self.username == self.UNKNOWN_USERNAME
