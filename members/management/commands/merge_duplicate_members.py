"""Merges duplicate accounts that were created next to a local account on the first SSO login.

In the past, anyone logging in via the c-base account who already had a local
account of the same name got a second account "<name>-2". By now the login
takes over the local account (see members/oidc.py); this command cleans up
the old pairs.

    python manage.py merge_duplicate_members           # only show
    python manage.py merge_duplicate_members --apply   # merge
    python manage.py merge_duplicate_members --apply alice-2
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from members.models import Member

SUFFIX = re.compile(r'^(?P<base>.+)-\d+$')


def find_pairs():
    """Pairs (local account, SSO duplicate), e.g. (alice, alice-2)."""
    pairs = []
    for duplicate in Member.objects.filter(oidc_sub__isnull=False).order_by('username'):
        match = SUFFIX.match(duplicate.username)
        if not match or match['base'] == Member.UNKNOWN_USERNAME:
            continue
        # Only accounts without an SSO link: a linked "alice" is a different person.
        original = Member.objects.filter(username=match['base'], oidc_sub__isnull=True).first()
        if original is not None:
            pairs.append((original, duplicate))
    return pairs


@transaction.atomic
def merge(original, duplicate):
    """Moves everything from the duplicate to the local account and deletes the duplicate."""
    # include_hidden: also relations without a reverse name, e.g. "uploaded by" on photos
    relations = [
        field for field in Member._meta.get_fields(include_hidden=True)
        if field.auto_created and not field.concrete and field.related_model._meta.auto_created is False
    ]
    for relation in relations:
        field = relation.field
        if relation.many_to_many:
            # e.g. the responsible members of a crate
            through = field.remote_field.through
            member_side, other_side = field.m2m_reverse_field_name(), f'{field.m2m_field_name()}_id'
            for row in through._base_manager.filter(**{member_side: duplicate}):
                if through._base_manager.filter(**{member_side: original, other_side: getattr(row, other_side)}).exists():
                    row.delete()
                else:
                    setattr(row, member_side, original)
                    row.save()
        else:
            # e.g. "uploaded by" on photos, entries in the admin log
            relation.related_model._base_manager.filter(**{field.name: duplicate}).update(**{field.name: original})
    original.groups.add(*duplicate.groups.all())
    original.user_permissions.add(*duplicate.user_permissions.all())

    sub = duplicate.oidc_sub
    for name in ('first_name', 'last_name', 'email'):
        # the details from the c-base account are the more recent ones
        setattr(original, name, getattr(duplicate, name) or getattr(original, name))
    original.is_staff = original.is_staff or duplicate.is_staff
    original.is_superuser = original.is_superuser or duplicate.is_superuser
    logins = [login for login in (original.last_login, duplicate.last_login) if login]
    original.last_login = max(logins, default=None)
    # delete first: oidc_sub is unique
    duplicate.delete()
    original.oidc_sub = sub
    original.save()


class Command(BaseCommand):
    help = 'Führt SSO-Doppelkonten („alice-2“) mit dem lokalen Konto gleichen Namens („alice“) zusammen.'

    def add_arguments(self, parser):
        parser.add_argument('usernames', nargs='*', help='Nur diese Doppelkonten, z. B. alice-2. Ohne Angabe: alle.')
        parser.add_argument('--apply', action='store_true', help='Wirklich zusammenführen. Ohne diese Angabe wird nur angezeigt.')

    def handle(self, *args, usernames, apply, **options):
        pairs = find_pairs()
        if usernames:
            unknown = set(usernames) - {duplicate.username for _, duplicate in pairs}
            if unknown:
                raise CommandError(f'Kein Doppelkonto zum Zusammenführen: {", ".join(sorted(unknown))}')
            pairs = [pair for pair in pairs if pair[1].username in usernames]
        if not pairs:
            self.stdout.write('Keine Doppelkonten gefunden.')
            return
        for original, duplicate in pairs:
            crates = duplicate.crates.count()
            self.stdout.write(
                f'{duplicate.username} -> {original.username}'
                f' ({crates} Crate{"s" if crates != 1 else ""} am Doppelkonto)'
            )
            if apply:
                merge(original, duplicate)
        if apply:
            self.stdout.write(self.style.SUCCESS(f'{len(pairs)} Doppelkonto/-konten zusammengeführt.'))
        else:
            self.stdout.write('Nichts geändert. Mit --apply zusammenführen.')
