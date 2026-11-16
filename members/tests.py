from unittest import mock

from django.http import HttpResponseRedirect
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Member
from .oidc import sync_member

CLAIMS = {
    'sub': 'abc-123', 'preferred_username': 'alice',
    'given_name': 'Alice', 'family_name': 'Example', 'email': 'alice@example.org',
}
OIDC = override_settings(OIDC_ISSUER_URL='https://idp.example.org', OIDC_CLIENT_ID='c-logistics')


def fake_client(claims=CLAIMS):
    client = mock.Mock()
    client.authorize_redirect.return_value = HttpResponseRedirect('https://idp.example.org/auth')
    client.authorize_access_token.return_value = {'userinfo': claims}
    return client


class SyncMemberTests(TestCase):
    def test_creates_member_without_password(self):
        member = sync_member(CLAIMS)
        self.assertEqual(member.username, 'alice')
        self.assertEqual(str(member), 'Alice Example')
        self.assertFalse(member.has_usable_password())

    def test_second_login_updates_instead_of_duplicating(self):
        sync_member(CLAIMS)
        member = sync_member({**CLAIMS, 'preferred_username': 'renamed', 'family_name': 'Neu'})
        self.assertEqual(Member.objects.count(), 1)
        self.assertEqual(member.username, 'alice')
        self.assertEqual(member.last_name, 'Neu')

    def test_does_not_take_over_local_account_with_same_username(self):
        local = Member.objects.create_superuser('alice', password='pw')
        member = sync_member(CLAIMS)
        self.assertNotEqual(member.pk, local.pk)
        self.assertEqual(member.username, 'alice-2')
        self.assertFalse(member.is_superuser)

    def test_falls_back_to_name_claim(self):
        member = sync_member({'sub': 'x', 'name': 'Bob van Beispiel'})
        self.assertEqual((member.first_name, member.last_name), ('Bob', 'van Beispiel'))
        self.assertEqual(member.username, 'x')


class LoginFlowTests(TestCase):
    def test_password_form_without_oidc(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'name="password"')
        self.assertEqual(self.client.get(reverse('oidc-login')).status_code, 404)

    @OIDC
    def test_sso_button_is_offered_above_the_local_password_form(self):
        response = self.client.get(reverse('login'), {'next': '/c/001A/'})
        self.assertContains(response, '/accounts/oidc/login/?next=/c/001A/')
        self.assertContains(response, 'mit c-base-account anmelden')
        self.assertContains(response, 'name="password"')

    @OIDC
    def test_local_account_can_still_log_in_with_password(self):
        Member.objects.create_user('lokal', password='geheim-123')
        response = self.client.post(reverse('login'), {'username': 'lokal', 'password': 'geheim-123', 'next': '/c/0000/'})
        self.assertRedirects(response, '/c/0000/')

    @OIDC
    def test_scan_login_returns_to_crate(self):
        client = fake_client()
        with mock.patch('members.oidc.get_client', return_value=client):
            response = self.client.get(reverse('oidc-login'), {'next': '/c/001A/'})
            self.assertEqual(response['Location'], 'https://idp.example.org/auth')
            self.assertEqual(client.authorize_redirect.call_args.args[1], 'http://testserver/accounts/oidc/callback/')
            response = self.client.get(reverse('oidc-callback'))
        self.assertRedirects(response, '/c/001A/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('crates:list')).status_code, 200)

    @OIDC
    def test_external_next_is_ignored(self):
        with mock.patch('members.oidc.get_client', return_value=fake_client()):
            self.client.get(reverse('oidc-login'), {'next': 'https://evil.example/'})
            response = self.client.get(reverse('oidc-callback'))
        self.assertRedirects(response, reverse('crates:list'))

    @OIDC
    @override_settings(PUBLIC_BASE_URL='https://crates.example.org')
    def test_redirect_uri_uses_public_base_url(self):
        client = fake_client()
        with mock.patch('members.oidc.get_client', return_value=client):
            self.client.get(reverse('oidc-login'))
        self.assertEqual(client.authorize_redirect.call_args.args[1], 'https://crates.example.org/accounts/oidc/callback/')

    @OIDC
    def test_provider_error_shows_message_and_does_not_log_in(self):
        from authlib.integrations.base_client import OAuthError
        client = fake_client()
        client.authorize_access_token.side_effect = OAuthError('access_denied')
        with mock.patch('members.oidc.get_client', return_value=client):
            response = self.client.get(reverse('oidc-callback'), follow=True)
        self.assertContains(response, 'fehlgeschlagen')
        self.assertNotIn('_auth_user_id', self.client.session)

    @OIDC
    def test_deactivated_member_cannot_log_in(self):
        member = sync_member(CLAIMS)
        member.is_active = False
        member.save()
        with mock.patch('members.oidc.get_client', return_value=fake_client()):
            self.client.get(reverse('oidc-callback'))
        self.assertNotIn('_auth_user_id', self.client.session)
