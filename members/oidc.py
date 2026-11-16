"""Anmeldung über OAuth2 / OpenID Connect (Authorization Code Flow)."""

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
    """Legt den Member zum OIDC-Konto an oder aktualisiert Name und E-Mail.

    Zugeordnet wird ausschließlich über das `sub`-Claim. Ein bestehendes lokales
    Konto mit gleichem Benutzernamen wird bewusst nicht übernommen.
    """
    sub = claims['sub']
    member = Member.objects.filter(oidc_sub=sub).first()
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
