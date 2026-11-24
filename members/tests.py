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
        self.assertEqual(Member.objects.exclude(username=Member.UNKNOWN_USERNAME).count(), 1)
        self.assertEqual(member.username, 'alice')
        self.assertEqual(member.last_name, 'Neu')

    def test_takes_over_local_account_with_same_username(self):
        local = Member.objects.create_superuser('alice', password='pw')
        member = sync_member(CLAIMS)
        self.assertEqual(member.pk, local.pk)
        self.assertEqual(member.oidc_sub, 'abc-123')
        self.assertEqual(member.email, 'alice@example.org')
        # Rechte und lokales Passwort bleiben
        self.assertTrue(member.is_superuser)
        self.assertTrue(member.check_password('pw'))
        self.assertEqual(Member.objects.filter(username__startswith='alice').count(), 1)

    def test_first_login_takes_over_the_reserved_account_with_its_crates(self):
        from crates.models import Crate

        reserved = Member.reserve('Alice')
        self.assertTrue(reserved.is_pending)
        crate = Crate.objects.create(name='Wartet auf Alice')
        crate.responsible.add(reserved)
        # der Provider schreibt den Namen klein: Es ist trotzdem dasselbe Konto
        member = sync_member(CLAIMS)
        self.assertEqual(member.pk, reserved.pk)
        self.assertFalse(member.is_pending)
        self.assertEqual(str(member), 'Alice Example')
        self.assertEqual(list(crate.responsible.all()), [member])
        self.assertEqual(Member.objects.filter(username__iexact='alice').count(), 1)

    def test_account_of_another_oidc_user_is_not_taken_over(self):
        first = sync_member(CLAIMS)
        second = sync_member({**CLAIMS, 'sub': 'other-456'})
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(second.username, 'alice-2')
        first.refresh_from_db()
        self.assertEqual(first.oidc_sub, 'abc-123')

    def test_placeholder_unbecannt_is_never_taken_over(self):
        unknown = Member.unknown()
        member = sync_member({'sub': 'evil', 'preferred_username': Member.UNKNOWN_USERNAME})
        self.assertNotEqual(member.pk, unknown.pk)
        self.assertEqual(member.username, 'unbecannt-2')
        unknown.refresh_from_db()
        self.assertIsNone(unknown.oidc_sub)
        self.assertFalse(unknown.is_active)

    def test_command_merges_old_duplicate_into_the_local_account(self):
        from django.contrib.auth.models import Group
        from django.core.management import call_command
        from crates.models import Crate, Photo
        import io

        local = Member.objects.create_superuser('alice', password='pw')
        duplicate = Member.objects.create(username='alice-2', oidc_sub='abc-123', email='alice@example.org', first_name='Alice')
        duplicate.groups.add(Group.objects.get(name=Member.MANAGER_GROUP))
        # ein fremdes Konto, das zufällig so aussieht, aber zu einem verknüpften „bob“ gehört
        Member.objects.create(username='bob', oidc_sub='bob-1')
        other = Member.objects.create(username='bob-2', oidc_sub='bob-2')
        shared, own = Crate.objects.create(name='Beide'), Crate.objects.create(name='Nur Doppel')
        shared.responsible.set([local, duplicate])
        own.responsible.set([duplicate, other])
        photo = Photo.objects.create(crate=own, uploaded_by=duplicate)

        out = io.StringIO()
        call_command('merge_duplicate_members', stdout=out)
        self.assertIn('alice-2 -> alice (2 Crates am Doppelkonto)', out.getvalue())
        self.assertNotIn('bob', out.getvalue())
        self.assertTrue(Member.objects.filter(username='alice-2').exists())

        call_command('merge_duplicate_members', '--apply', stdout=io.StringIO())
        self.assertFalse(Member.objects.filter(username='alice-2').exists())
        local.refresh_from_db()
        self.assertEqual((local.oidc_sub, local.email, local.first_name), ('abc-123', 'alice@example.org', 'Alice'))
        self.assertTrue(local.is_superuser)
        self.assertTrue(local.check_password('pw'))
        self.assertTrue(local.is_manager)
        self.assertEqual(list(shared.responsible.all()), [local])
        self.assertEqual(set(own.responsible.all()), {local, other})
        photo.refresh_from_db()
        self.assertEqual(photo.uploaded_by, local)
        # der nächste SSO-Login landet im zusammengeführten Konto
        self.assertEqual(sync_member(CLAIMS).pk, local.pk)
        self.assertTrue(Member.objects.filter(username='bob-2').exists())

    def test_falls_back_to_name_claim(self):
        member = sync_member({'sub': 'x', 'name': 'Bob van Beispiel'})
        self.assertEqual((member.first_name, member.last_name), ('Bob', 'van Beispiel'))
        self.assertEqual(member.username, 'x')


# Unabhängig von einer lokalen .env: ohne Provider und ohne feste Adresse starten.
@override_settings(OIDC_ISSUER_URL='', OIDC_CLIENT_ID='', OIDC_PROVIDER_NAME='c-base-account', PUBLIC_BASE_URL='')
class LoginFlowTests(TestCase):
    def test_password_form_without_oidc(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'name="password"')
        self.assertEqual(self.client.get(reverse('oidc-login')).status_code, 404)

    @OIDC
    def test_sso_button_is_offered_above_the_local_password_form(self):
        response = self.client.get(reverse('login'), {'next': '/001A'})
        self.assertContains(response, '/accounts/oidc/login/?next=/001A')
        self.assertContains(response, 'mit c-base-account anmelden')
        self.assertContains(response, 'name="password"')

    @OIDC
    def test_local_account_can_still_log_in_with_password(self):
        Member.objects.create_user('lokal', password='geheim-123')
        response = self.client.post(reverse('login'), {'username': 'lokal', 'password': 'geheim-123', 'next': '/0000'})
        self.assertRedirects(response, '/0000')

    @OIDC
    def test_scan_login_returns_to_crate(self):
        client = fake_client()
        with mock.patch('members.oidc.get_client', return_value=client):
            response = self.client.get(reverse('oidc-login'), {'next': '/001A'})
            self.assertEqual(response['Location'], 'https://idp.example.org/auth')
            self.assertEqual(client.authorize_redirect.call_args.args[1], 'http://testserver/accounts/oidc/callback/')
            response = self.client.get(reverse('oidc-callback'))
        self.assertRedirects(response, '/001A', fetch_redirect_response=False)
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
