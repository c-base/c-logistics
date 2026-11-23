import re

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
    # Was als Nick vorgemerkt werden darf: Buchstaben, Ziffern, Punkt, Binde- und Unterstrich.
    NICK = re.compile(r'[\w.-]{1,64}')

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

    @classmethod
    def reserve(cls, username):
        """Merkt ein Konto für jemanden vor, der sich noch nie angemeldet hat.

        Es hat nur den Benutzernamen. Beim ersten SSO-Login übernimmt es, wer beim
        Provider so heißt (siehe members/oidc.py). Ob es den Nick wirklich gibt,
        lässt sich hier nicht prüfen; mit einem Member-Verzeichnis (LDAP o. Ä.)
        wäre das die Stelle dafür. Wirft ValueError bei unbrauchbaren Namen.
        """
        username = username.strip()
        if not cls.NICK.fullmatch(username):
            raise ValueError('Ein Nick besteht aus Buchstaben, Ziffern, Punkt, Binde- und Unterstrich.')
        if username.lower() == cls.UNKNOWN_USERNAME:
            raise ValueError('„unbecannt“ ist der Platzhalter und kein Member.')
        member = cls.find_by_username(username)
        if member is None:
            member = cls(username=username)
            member.set_unusable_password()
            member.save()
        return member

    @classmethod
    def find_by_username(cls, username, **filters):
        """Das Konto mit diesem Namen; Groß- und Kleinschreibung zählt nur bei mehreren Treffern."""
        members = cls.objects.filter(**filters)
        return members.filter(username=username).first() or members.filter(username__iexact=username).first()

    @property
    def is_pending(self):
        """Vorgemerkt und noch nie angemeldet: kein SSO-Konto, kein Passwort."""
        return self.oidc_sub is None and not self.has_usable_password() and not self.is_unknown

    @property
    def label(self):
        """Name für Auswahllisten, mit Hinweis bei vorgemerkten Konten."""
        return f'{self} (noch nie angemeldet)' if self.is_pending else str(self)

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
