"""Login via OAuth2 / OpenID Connect (authorization code flow)."""

from authlib.integrations.django_client import OAuth
from django.conf import settings

from .models import Member

_oauth = None


def is_enabled():
    return bool(settings.OIDC_ISSUER_URL and settings.OIDC_CLIENT_ID)


def get_client():
    global _oauth
    if _oauth is None:
        _oauth = OAuth()
        _oauth.register(
            'oidc',
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET,
            server_metadata_url=f'{settings.OIDC_ISSUER_URL}/.well-known/openid-configuration',
            client_kwargs={'scope': settings.OIDC_SCOPE},
        )
    return _oauth.oidc


def _free_username(wanted):
    max_length = Member._meta.get_field('username').max_length
    wanted = wanted[:max_length]
    username, counter = wanted, 1
    while Member.objects.filter(username=username).exists():
        counter += 1
        suffix = f'-{counter}'
        username = wanted[:max_length - len(suffix)] + suffix
    return username


def sync_member(claims):
    """Creates the member for the OIDC account or updates name and e-mail.

    An account is recognised by the `sub` claim. On the first login the member
    takes over an existing local account with the same username, including its
    permissions and crates, instead of getting a second one ("alice-2") next
    to it. This assumes that the provider hands out usernames only to their
    rightful owners.
    """
    sub = claims['sub']
    member = Member.objects.filter(oidc_sub=sub).first()
    if member is None and claims.get('preferred_username'):
        # Never taken over are the placeholder "unbecannt" and accounts that
        # already belong to another OIDC account.
        # This is also how someone gets their account who was reserved as a
        # responsible member before ever logging in (Member.reserve).
        member = Member.find_by_username(claims['preferred_username'], oidc_sub__isnull=True)
        if member is not None and member.is_unknown:
            member = None
        if member is not None:
            member.oidc_sub = sub
    if member is None:
        wanted = claims.get('preferred_username') or claims.get('email') or sub
        member = Member(oidc_sub=sub, username=_free_username(wanted))
        member.set_unusable_password()

    first, last = claims.get('given_name', ''), claims.get('family_name', '')
    if not (first or last) and claims.get('name'):
        first, _, last = claims['name'].partition(' ')
    member.first_name = first[:150]
    member.last_name = last[:150]
    member.email = claims.get('email', '')
    member.save()
    return member
