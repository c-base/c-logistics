import re

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.functional import cached_property


class Member(AbstractUser):
    """A member is both a login account and a possible responsible member for crates."""

    # Placeholder for crates whose responsible members nobody knows. Not a real
    # account: inactive and without a password, created by a migration.
    UNKNOWN_USERNAME = 'unbecannt'
    # The "Manager" role is a group (created by a migration, assigned in the admin).
    MANAGER_GROUP = 'Manager'
    # What may be reserved as a nick: letters, digits, dot, hyphen and underscore.
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
        """The placeholder "unbecannt"."""
        member, created = cls.objects.get_or_create(username=cls.UNKNOWN_USERNAME, defaults={'is_active': False})
        if created:
            member.set_unusable_password()
            member.save(update_fields=['password'])
        return member

    @classmethod
    def reserve(cls, username):
        """Reserves an account for someone who has never logged in.

        It only has the username. On the first SSO login it is taken over by whoever
        has that name at the provider (see members/oidc.py). Whether the nick really
        exists cannot be checked here; with a member directory (LDAP or similar)
        this would be the place for it. Raises ValueError for unusable names.
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
        """The account with this name; case only matters when there are several matches."""
        members = cls.objects.filter(**filters)
        return members.filter(username=username).first() or members.filter(username__iexact=username).first()

    @property
    def is_pending(self):
        """Reserved and never logged in: no SSO account, no password."""
        return self.oidc_sub is None and not self.has_usable_password() and not self.is_unknown

    @property
    def label(self):
        """Name for selection lists, with a note for reserved accounts."""
        return f'{self} (noch nie angemeldet)' if self.is_pending else str(self)

    @property
    def is_unknown(self):
        return self.username == self.UNKNOWN_USERNAME

    @cached_property
    def is_manager(self):
        """Managers may e.g. remind the responsible members by mail. Superusers always are managers."""
        return self.is_active and (self.is_superuser or self.groups.filter(name=self.MANAGER_GROUP).exists())

    @property
    def email_address(self):
        """The address from the c-base account; if missing, <username>@c-base.org."""
        return self.email or f'{self.username}@{settings.MEMBER_EMAIL_DOMAIN}'
