from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.functional import cached_property


class Member(AbstractUser):
    """Ein Member ist zugleich Login-Konto und möglicher Verantwortlicher für Crates."""

    # Platzhalter für Crates, deren Verantwortliche niemand kennt. Kein echtes
    # Konto: inaktiv und ohne Passwort, angelegt per Migration.
    UNKNOWN_USERNAME = 'unbecannt'
    # Die Rolle „Manager“ ist eine Gruppe (per Migration angelegt, im Admin zugewiesen).
    MANAGER_GROUP = 'Manager'

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

    @cached_property
    def is_manager(self):
        """Manager dürfen z. B. die Verantwortlichen per Mail erinnern. Superuser sind es immer."""
        return self.is_active and (self.is_superuser or self.groups.filter(name=self.MANAGER_GROUP).exists())

    @property
    def email_address(self):
        """Die Adresse aus dem c-base-Account; fehlt sie, <Nutzername>@c-base.org."""
        return self.email or f'{self.username}@{settings.MEMBER_EMAIL_DOMAIN}'
