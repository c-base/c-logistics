import logging

from authlib.integrations.base_client import OAuthError
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.http import Http404
from django.shortcuts import redirect, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from . import oidc
from .forms import LoginForm

logger = logging.getLogger(__name__)

NEXT_SESSION_KEY = 'oidc_next'


class MemberLoginView(LoginView):
    """Shows the SSO button when OIDC is configured, and the form for local accounts."""

    authentication_form = LoginForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['oidc_enabled'] = oidc.is_enabled()
        context['oidc_provider_name'] = settings.OIDC_PROVIDER_NAME
        context['oidc_error'] = self.request.GET.get('oidc_error')
        return context


def oidc_login(request):
    if not oidc.is_enabled():
        raise Http404
    request.session[NEXT_SESSION_KEY] = request.GET.get('next', '')
    callback = reverse('oidc-callback')
    # Behind a reverse proxy the public address is more reliable than the request.
    redirect_uri = settings.PUBLIC_BASE_URL + callback if settings.PUBLIC_BASE_URL else request.build_absolute_uri(callback)
    return oidc.get_client().authorize_redirect(request, redirect_uri)


def oidc_callback(request):
    if not oidc.is_enabled():
        raise Http404
    client = oidc.get_client()
    try:
        token = client.authorize_access_token(request)
        claims = token.get('userinfo') or client.userinfo(token=token)
        member = oidc.sync_member(claims)
    except (OAuthError, KeyError) as error:
        logger.warning('OIDC-Anmeldung fehlgeschlagen: %r', error)
        return redirect(f"{reverse('login')}?oidc_error=1")
    if not member.is_active:
        return redirect(f"{reverse('login')}?oidc_error=1")

    login(request, member, backend='django.contrib.auth.backends.ModelBackend')
    next_url = request.session.pop(NEXT_SESSION_KEY, '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = resolve_url(settings.LOGIN_REDIRECT_URL)
    return redirect(next_url)
