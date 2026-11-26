"""Reminder mails to the responsible members of crates with "Needs attention"."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from .labels import public_url
from .models import Crate

logger = logging.getLogger(__name__)


@dataclass
class Reminder:
    """One mail: one member and all of their crates that need attention."""

    member: object
    address: str
    crates: list = field(default_factory=list)


@dataclass
class Plan:
    reminders: list = field(default_factory=list)
    # reminded recently: no new mail yet
    recent: list = field(default_factory=list)
    # only "unbecannt" is responsible: nobody one could write to
    unreachable: list = field(default_factory=list)

    @property
    def crate_count(self):
        return len({crate.pk for reminder in self.reminders for crate in reminder.crates})


def make_plan(now=None):
    """Who would get a mail for which crates. Sends nothing."""
    now = now or timezone.now()
    threshold = now - timedelta(days=settings.REMINDER_INTERVAL_DAYS)
    plan, by_member = Plan(), {}
    crates = Crate.objects.filter(needs_attention=True).prefetch_related('responsible').order_by('code')
    for crate in crates:
        if crate.attention_reminded_at and crate.attention_reminded_at > threshold:
            plan.recent.append(crate)
            continue
        members = [member for member in crate.responsible.all() if not member.is_unknown]
        if not members:
            plan.unreachable.append(crate)
            continue
        for member in members:
            reminder = by_member.setdefault(member.pk, Reminder(member, member.email_address))
            reminder.crates.append(crate)
    plan.reminders = sorted(by_member.values(), key=lambda reminder: str(reminder.member).lower())
    return plan


def _subject(crates):
    if len(crates) == 1:
        return f'c-base cargo crate {crates[0].code} braucht Aufmerksamkeit'
    return f'{len(crates)} deiner c-base cargo crates brauchen Aufmerksamkeit'


def _body(reminder, sender, request):
    crates = reminder.crates
    if len(crates) == 1:
        intro = 'eine deiner c-base cargo crates braucht Aufmerksamkeit:'
    else:
        intro = f'{len(crates)} deiner c-base cargo crates brauchen Aufmerksamkeit:'
    blocks = []
    for crate in crates:
        note = crate.attention_note.strip() or '(ohne Bemerkung)'
        lines = [f'{crate.code} {crate.name}', *note.splitlines(), public_url(crate, request)]
        blocks.append('\n'.join(f'  {line}' for line in lines))
    return '\n\n'.join([
        f'Hallo {reminder.member.first_name or reminder.member.username},',
        intro,
        *blocks,
        'Bitte schau nach. Ist das Problem behoben, nimm auf der Seite der Crate\n'
        'unter „Bearbeiten“ den Haken „Needs attention“ wieder heraus.',
        f'Diese Mail hat {sender} über c-logistics ausgelöst. Antworten gehen an {sender}.',
    ]) + '\n'


def send_reminders(plan, sender, request=None):
    """Sends one mail per member and records on the crates that a reminder went out.

    Returns (sent, failed), each a list of reminders.
    A crate counts as reminded as soon as one of its mails was accepted.
    """
    sent, failed = [], []
    connection = get_connection()
    for reminder in plan.reminders:
        message = EmailMessage(
            subject=_subject(reminder.crates),
            body=_body(reminder, sender, request),
            to=[reminder.address],
            reply_to=[sender.email_address],
            connection=connection,
        )
        try:
            message.send()
        except Exception:  # an error with one mail should not hold up the others
            logger.exception('Erinnerung an %s konnte nicht verschickt werden', reminder.address)
            failed.append(reminder)
        else:
            sent.append(reminder)
    reminded = {crate.pk for reminder in sent for crate in reminder.crates}
    # update() instead of save(): the crate's "last changed" should not change because of this
    Crate.objects.filter(pk__in=reminded).update(attention_reminded_at=timezone.now())
    return sent, failed
