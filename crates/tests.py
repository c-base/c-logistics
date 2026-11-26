from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.utils import timezone
from unittest import mock
import csv
import io
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, ImageOps
from django.urls import reverse

from .labels import FONTS, labels_ql_raster, nfc_logo, public_url, render_label
from .models import Crate, Item, Photo, Tag, format_code


# Independent of a local .env.
@override_settings(PUBLIC_BASE_URL='', LABEL_FONT='baijamjuree', LABEL_WIDTH_PX=696, PRINT_COPIES=1)
class CrateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user('alice', password='pw')
        cls.other = get_user_model().objects.create_user('bob', password='pw')
        cls.crate = Crate.objects.create(name='Kabelkiste')
        cls.crate.responsible.add(cls.member)
        Item.objects.create(crate=cls.crate, name='HDMI-Kabel', quantity=4)
        cls.other_crate = Crate.objects.create(name='Werkzeug')
        cls.other_crate.responsible.add(cls.other)

    def setUp(self):
        self.client.force_login(self.member)

    def make_manager(self):
        self.member.groups.add(Group.objects.get(name='Manager'))

    def test_only_managers_create_crates(self):
        url = reverse('crates:create')
        # no link, no form, no creating
        self.assertNotContains(self.client.get(reverse('crates:list')), f'href="{url}"')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'name': 'Heimlich', 'size': '400x300'}).status_code, 403)
        self.assertFalse(Crate.objects.filter(name='Heimlich').exists())
        # every member may still edit
        self.assertEqual(self.client.get(reverse('crates:update', args=[self.crate.code])).status_code, 200)
        self.make_manager()
        self.assertContains(self.client.get(reverse('crates:list')), f'href="{url}"', count=2)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_detail_links_to_the_neighbouring_crates(self):
        last = Crate.objects.create(name='Letzte')
        first, middle = self.client.get(self.crate.get_absolute_url()), self.client.get(self.other_crate.get_absolute_url())
        # before 0001 there is only 0000, created by a migration, and nothing before that
        self.assertContains(first, 'rel="prev" href="/0000"')
        self.assertNotContains(self.client.get('/0000'), 'rel="prev"')
        self.assertContains(first, f'rel="next" href="{self.other_crate.get_absolute_url()}"')
        self.assertContains(middle, f'rel="prev" href="{self.crate.get_absolute_url()}"')
        self.assertContains(middle, f'rel="next" href="{last.get_absolute_url()}"')
        self.assertNotContains(self.client.get(last.get_absolute_url()), 'rel="next"')

    def test_codes_are_sequential_four_digit_hex(self):
        self.assertEqual(self.crate.code, '0001')
        self.assertEqual(self.other_crate.code, '0002')
        self.assertEqual(format_code(26), '001A')
        self.assertEqual(format_code(0xFFFF), 'FFFF')

    def test_0000_is_dev_null_and_never_assigned_to_a_new_crate(self):
        self.assertEqual(Crate.objects.get(code='0000').name, '/dev/null')
        self.assertContains(self.client.get('/0000'), '/dev/null')
        Crate.objects.all().delete()
        self.assertEqual(Crate.objects.create(name='Erste').code, '0001')

    def test_numbering_continues_in_hex_after_nine(self):
        Crate.objects.create(name='Vorgänger', code='0009')
        self.assertEqual(Crate.objects.create(name='Zehnte').code, '000A')
        Crate.objects.create(name='Vorgänger', code='00FF')
        self.assertEqual(Crate.objects.create(name='Nächste').code, '0100')

    def test_code_survives_editing(self):
        self.crate.name = 'Umbenannt'
        self.crate.save()
        self.assertEqual(self.crate.code, '0001')

    def test_numbers_run_out_after_ffff(self):
        Crate.objects.create(name='Letzte', code='FFFF')
        with self.assertRaises(OverflowError):
            Crate.objects.create(name='Zu viel')

    def test_scan_url_ends_with_code(self):
        self.assertEqual(self.crate.get_absolute_url(), f'/{self.crate.code}')

    def test_scan_requires_login_and_returns_to_crate(self):
        self.client.logout()
        url = self.crate.get_absolute_url()
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_detail_shows_content_and_accepts_short_code(self):
        response = self.client.get('/1')
        self.assertContains(response, 'HDMI-Kabel')
        self.assertContains(response, 'alice')

    def test_unknown_code_is_404(self):
        self.assertEqual(self.client.get('/0BAD').status_code, 404)

    def test_lowercase_code_opens_crate(self):
        crate = Crate.objects.create(name='Hex', code='00AF')
        crate.responsible.add(self.member)
        self.assertContains(self.client.get('/00af'), 'Hex')

    def test_search_finds_crate_by_code(self):
        response = self.client.get(reverse('crates:list'), {'q': '2'})
        self.assertContains(response, 'Werkzeug')
        self.assertNotContains(response, 'Kabelkiste')

    def test_search_finds_crate_by_content(self):
        response = self.client.get(reverse('crates:list'), {'q': 'hdmi'})
        self.assertContains(response, 'Kabelkiste')
        self.assertNotContains(response, 'Werkzeug')

    def test_mine_filter(self):
        response = self.client.get(reverse('crates:list'), {'mine': '1'})
        self.assertContains(response, 'Kabelkiste')
        self.assertNotContains(response, 'Werkzeug')

    def test_create_crate_with_multiple_responsible(self):
        self.make_manager()
        response = self.client.post(reverse('crates:create'), {
            'name': 'Lötkram', 'size': '400x300',
            'responsible': [self.member.pk, self.other.pk],
        })
        crate = Crate.objects.get(name='Lötkram')
        self.assertRedirects(response, crate.get_absolute_url())
        self.assertEqual(crate.responsible.count(), 2)

    def test_crate_without_responsible_member_belongs_to_unbecannt(self):
        self.make_manager()
        self.client.post(reverse('crates:create'), {'name': 'Herrenlos', 'size': '400x300'})
        crate = Crate.objects.get(name='Herrenlos')
        self.assertEqual([member.username for member in crate.responsible.all()], ['unbecannt'])
        self.assertContains(self.client.get(crate.get_absolute_url()), 'unbecannt')

    def test_unbecannt_goes_away_as_soon_as_a_member_is_responsible(self):
        self.make_manager()
        unknown = get_user_model().unknown()
        data = {'name': 'Gefunden', 'size': '400x300', 'responsible': [unknown.pk, self.member.pk]}
        self.client.post(reverse('crates:create'), data)
        crate = Crate.objects.get(name='Gefunden')
        self.assertEqual(list(crate.responsible.all()), [self.member])
        # … and comes back when the last member is removed
        self.client.post(reverse('crates:update', args=[crate.code]), {'name': 'Gefunden', 'size': '400x300'})
        self.assertEqual(list(crate.responsible.all()), [unknown])

    def test_unbecannt_is_a_placeholder_that_cannot_log_in_and_heads_the_list(self):
        self.make_manager()
        unknown = get_user_model().unknown()
        self.assertFalse(unknown.is_active)
        self.assertFalse(unknown.has_usable_password())
        self.assertTrue(unknown.is_unknown)
        self.assertEqual(get_user_model().objects.filter(username='unbecannt').count(), 1)
        response = self.client.get(reverse('crates:create'))
        choices = [str(label) for _, label in response.context['form'].fields['responsible'].choices]
        self.assertEqual(choices[0], 'unbecannt')
        self.assertContains(response, f'data-unknown="{unknown.pk}"')

    def shown_members(self, response):
        return [label for _, label in response.context['form'].fields['responsible'].widget.choices]

    def test_form_shows_only_unbecannt_oneself_and_the_chosen_members_as_checkboxes(self):
        self.make_manager()
        response = self.client.get(reverse('crates:create'))
        self.assertEqual(self.shown_members(response), ['unbecannt', 'alice'])
        self.assertNotContains(response, f'value="{self.other.pk}"')
        self.assertContains(response, f'data-search-url="{reverse("crates:member-search")}"')
        # on someone else's crate its responsible members are shown as well
        response = self.client.get(reverse('crates:update', args=[self.other_crate.code]))
        self.assertEqual(self.shown_members(response), ['unbecannt', 'alice', 'bob'])
        self.assertContains(response, f'value="{self.other.pk}"')
        # after a form error the ones chosen via the search stay
        response = self.client.post(reverse('crates:create'), {'name': '', 'responsible': [self.other.pk, 'x']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.shown_members(response), ['unbecannt', 'alice', 'bob'])

    def test_member_search_finds_by_any_part_of_the_name(self):
        carol = get_user_model().objects.create_user('carol', password='pw', first_name='Carol', last_name='Danvers')
        url = reverse('crates:member-search')

        def found(query):
            return [member['username'] for member in self.client.get(url, {'q': query}).json()['results']]

        self.assertEqual(found('LIC'), ['alice'])
        self.assertEqual(found('dan car'), ['carol'])
        self.assertEqual(found('o'), ['bob', 'carol'])
        self.assertEqual(self.client.get(url, {'q': 'car'}).json()['results'], [
            {'id': carol.pk, 'label': 'Carol Danvers', 'username': 'carol'},
        ])
        # the placeholder is always there as a checkbox and never a search hit
        self.assertEqual(found('unbe'), [])
        self.assertEqual(found(''), [])
        self.assertEqual(found('zzz'), [])
        self.client.logout()
        self.assertEqual(self.client.get(url, {'q': 'a'}).status_code, 302)

    def test_managers_reserve_members_who_never_logged_in(self):
        url, users = reverse('crates:member-add'), get_user_model().objects
        # only managers get the offer and may reserve
        self.assertNotContains(self.client.get(reverse('crates:update', args=[self.crate.code])), 'data-add-url')
        self.assertEqual(self.client.post(url, {'username': 'dave'}).status_code, 403)
        self.assertFalse(users.filter(username='dave').exists())
        self.member.groups.add(Group.objects.get(name='Manager'))
        self.assertContains(self.client.get(reverse('crates:create')), f'data-add-url="{url}"')

        response = self.client.post(url, {'username': ' dave '})
        dave = users.get(username='dave')
        self.assertEqual(response.json(), {'id': dave.pk, 'label': 'dave (noch nie angemeldet)', 'username': 'dave'})
        self.assertTrue(dave.is_pending)
        self.assertFalse(dave.has_usable_password())
        self.assertEqual(dave.email_address, 'dave@c-base.org')
        # a second time, even spelled differently, creates no second account
        self.assertEqual(self.client.post(url, {'username': 'Dave'}).json()['id'], dave.pk)
        self.assertEqual(self.client.post(url, {'username': 'BOB'}).json(), {'id': self.other.pk, 'label': 'bob', 'username': 'bob'})
        self.assertEqual(users.filter(username__iexact='dave').count(), 1)
        for bad in ['', 'zwei worte', 'a@b', 'unbecannt', 'Unbecannt', 'x' * 65]:
            self.assertEqual(self.client.post(url, {'username': bad}).status_code, 400, bad)

        # the reserved member can be chosen and is marked in search and form
        found = self.client.get(reverse('crates:member-search'), {'q': 'dav'}).json()['results']
        self.assertEqual([member['label'] for member in found], ['dave (noch nie angemeldet)'])
        data = {'name': 'Für Dave', 'size': '400x300', 'responsible': [dave.pk]}
        self.client.post(reverse('crates:create'), data)
        crate = Crate.objects.get(name='Für Dave')
        self.assertEqual(list(crate.responsible.all()), [dave])
        response = self.client.get(reverse('crates:update', args=[crate.code]))
        self.assertIn('dave (noch nie angemeldet)', self.shown_members(response))

    def make_tags(self, names):
        return [Tag.objects.get_or_create(scope=scope, value=value)[0] for scope, value in Tag.parse_many(names)]

    def tag(self, crate, names):
        """Saves the crate through the form with exactly these tags."""
        responsible = list(crate.responsible.values_list('pk', flat=True))
        tags = [tag.pk for tag in self.make_tags(names)]
        data = {'name': crate.name, 'size': crate.size, 'responsible': responsible, 'tags': tags}
        return self.client.post(reverse('crates:update', args=[crate.code]), data)

    def listed(self, **query):
        return list(self.client.get(reverse('crates:list'), query).context['object_list'])

    def test_tags_are_picked_from_the_fixed_selection_and_shown(self):
        self.make_tags('eva:40c3 eva:camp transport:1')
        form = self.client.get(reverse('crates:update', args=[self.crate.code])).context['form']
        self.assertEqual([label for _, label in form.fields['tags'].choices], ['eva:40c3', 'eva:camp', 'transport:1'])
        self.assertLess(list(form.fields).index('tags'), list(form.fields).index('needs_attention'))
        self.tag(self.crate, 'eva:40c3 transport:1')
        self.assertEqual([str(tag) for tag in self.crate.tags.all()], ['eva:40c3', 'transport:1'])
        response = self.client.get(self.crate.get_absolute_url())
        self.assertContains(response, f'href="{reverse("crates:list")}?tag=transport%3A1"')
        self.assertContains(self.client.get(reverse('crates:list')), '<span class="scope">eva:</span>40c3')
        # the form creates no new tag
        data = {'name': self.crate.name, 'size': self.crate.size, 'tags': [9999]}
        response = self.client.post(reverse('crates:update', args=[self.crate.code]), data)
        self.assertContains(response, 'field-error')
        self.assertEqual(Tag.objects.count(), 3)

    def test_what_is_not_a_scoped_tag_is_rejected(self):
        for bad in ['40c3', 'eva:', ':40c3', 'eva:40c3:x', 'eva:40 c3', 'e' * 31 + ':x']:
            with self.assertRaises(ValueError, msg=bad):
                Tag.parse_many(f'transport:1 {bad}')
        self.assertEqual(Tag.parse_many('EVA:40c3, transport:1  eva:40c3'), [('eva', '40c3'), ('transport', '1')])

    def test_tags_stay_when_no_crate_carries_them(self):
        self.tag(self.crate, 'eva:40c3 transport:1')
        self.tag(self.crate, '')
        self.assertEqual(self.crate.tags.count(), 0)
        self.assertEqual([str(tag) for tag in Tag.objects.all()], ['eva:40c3', 'transport:1'])
        self.assertContains(self.client.get(reverse('crates:list')), '<option value="transport:1">')

    def manage(self, **data):
        return self.client.post(reverse('crates:tags'), data, follow=True)

    def test_managers_add_rename_and_delete_tags(self):
        url = reverse('crates:tags')
        # managers only: no link, no access
        self.assertNotContains(self.client.get(reverse('crates:list')), f'href="{url}"')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'action': 'add', 'names': 'eva:40c3'}).status_code, 403)
        self.assertEqual(Tag.objects.count(), 0)
        self.member.groups.add(Group.objects.get(name='Manager'))
        self.assertContains(self.client.get(reverse('crates:list')), f'href="{url}"')
        self.assertContains(self.client.get(reverse('crates:create')), 'Tags verwalten')

        response = self.manage(action='add', names='EVA:40c3 transport:1, transport:2')
        self.assertContains(response, 'Angelegt: eva:40c3, transport:1, transport:2.')
        self.assertContains(self.manage(action='add', names='eva:40c3'), 'Diese Tags gab es schon.')
        response = self.manage(action='add', names='transport:3 ohnebereich')
        self.assertContains(response, 'ist kein Tag')
        self.assertContains(response, 'value="transport:3 ohnebereich"')
        self.assertEqual([str(tag) for tag in Tag.objects.all()], ['eva:40c3', 'transport:1', 'transport:2'])

        self.tag(self.crate, 'eva:40c3 transport:1')
        self.assertContains(self.client.get(url), '1 Crate</a>')
        one = Tag.find('transport:1')
        self.assertContains(self.manage(action='rename', tag=one.pk, name='Transport:Lkw'), 'transport:1 heißt jetzt transport:lkw.')
        self.assertEqual([str(tag) for tag in self.crate.tags.all()], ['eva:40c3', 'transport:lkw'])
        self.assertContains(self.manage(action='rename', tag=one.pk, name='transport:2'), 'transport:2 gibt es schon.')
        self.assertContains(self.manage(action='rename', tag=one.pk, name='unsinn'), 'ist kein Tag')
        self.assertEqual(str(Tag.objects.get(pk=one.pk)), 'transport:lkw')

        self.assertContains(self.manage(action='delete', tag=one.pk), 'transport:lkw gelöscht.')
        self.assertEqual([str(tag) for tag in self.crate.tags.all()], ['eva:40c3'])
        self.assertEqual(self.client.post(url, {'action': 'delete', 'tag': one.pk}).status_code, 404)

    def test_list_filters_by_tag(self):
        self.tag(self.crate, 'eva:40c3 transport:1')
        self.tag(self.other_crate, 'eva:40c3 transport:2')
        self.assertEqual(self.listed(tag='eva:40c3'), [self.crate, self.other_crate])
        self.assertEqual(self.listed(tag='Transport:2'), [self.other_crate])
        self.assertEqual(self.listed(tag=['eva:40c3', 'transport:1']), [self.crate])
        # also two tags of the same scope: the crate then has to carry both
        self.assertEqual(self.listed(tag=['transport:1', 'transport:2']), [])
        self.bulk([self.crate], 'transport:2')
        self.assertEqual(self.listed(tag=['transport:1', 'transport:2']), [self.crate])
        response = self.client.get(reverse('crates:list'), {'tag': ['', 'transport:2', 'Transport:2', 'eva:40c3']})
        self.assertEqual(response.context['selected_tags'], ['transport:2', 'eva:40c3'])
        self.assertContains(response, '<input type="checkbox" name="tag" value="transport:2" checked>')
        self.assertContains(response, '<input type="checkbox" name="tag" value="transport:1">')
        self.crate.tags.remove(Tag.find('transport:2'))
        self.assertEqual(self.listed(tag='transport:9'), [])
        self.assertEqual(self.listed(tag='unsinn'), [])
        self.assertEqual(self.listed(tag=''), list(Crate.objects.all()))
        # the search finds tags too, and both filters apply together
        self.assertEqual(self.listed(q='40c3'), [self.crate, self.other_crate])
        self.assertEqual(self.listed(q='transport'), [self.crate, self.other_crate])
        self.assertEqual(self.listed(tag='eva:40c3', mine='1'), [self.crate])
        response = self.client.get(reverse('crates:list'), {'tag': 'eva:40c3'})
        self.assertContains(response, '2 Crates mit')
        self.assertContains(response, '<input type="checkbox" name="tag" value="eva:40c3" checked>')

    def test_paging_keeps_the_filters(self):
        with mock.patch('crates.views.CrateListView.paginate_by', 1):
            self.tag(self.crate, 'eva:40c3')
            self.tag(self.other_crate, 'eva:40c3')
            response = self.client.get(reverse('crates:list'), {'tag': 'eva:40c3', 'q': 'e'})
            self.assertContains(response, 'href="?tag=eva%3A40c3&amp;q=e&amp;page=2"')
            response = self.client.get(reverse('crates:list'))
            self.assertContains(response, 'href="?page=2"')

    def bulk(self, crates, tags, action='add', create=True, **extra):
        if create:
            self.make_tags(tags)
        data = {'c': [crate.code for crate in crates], 'tags': tags, 'action': action, **extra}
        return self.client.post(reverse('crates:bulk-tag'), data, follow=True)

    def tags_of(self, crate):
        return [str(tag) for tag in crate.tags.all()]

    def test_tags_are_set_and_removed_on_all_picked_crates(self):
        self.tag(self.crate, 'eva:40c3')
        response = self.bulk([self.crate, self.other_crate], 'Transport:1 eva:40c3', next='/?tag=eva%3A40c3')
        self.assertEqual(response.redirect_chain, [('/?tag=eva%3A40c3', 302)])
        self.assertContains(response, 'transport:1, eva:40c3 an 2 Crates gesetzt.')
        self.assertEqual(self.tags_of(self.crate), ['eva:40c3', 'transport:1'])
        self.assertEqual(self.tags_of(self.other_crate), ['eva:40c3', 'transport:1'])
        # the responsible members stay, unlike when saving through the form without a selection
        self.assertEqual(list(self.other_crate.responsible.all()), [self.other])
        # the bar offers the tags for selection
        self.assertContains(self.client.get(reverse('crates:list')), 'id="bulk-tags"')

        response = self.bulk([self.other_crate], 'transport:1', action='remove')
        self.assertContains(response, 'transport:1 von 1 Crate entfernt.')
        self.assertEqual(self.tags_of(self.other_crate), ['eva:40c3'])
        self.assertEqual(self.tags_of(self.crate), ['eva:40c3', 'transport:1'])
        self.bulk([self.crate], 'transport:1', action='remove')
        # the tag itself stays in the selection
        self.assertTrue(Tag.objects.filter(scope='transport', value='1').exists())

    def test_bulk_tagging_needs_crates_and_a_known_tag(self):
        self.make_tags('eva:40c3')
        self.assertContains(self.bulk([], 'eva:40c3'), 'Bitte Crates auswählen')
        self.assertContains(self.bulk([self.crate], ''), 'Bitte Crates auswählen')
        response = self.bulk([self.crate], 'eva:40c3 transport:9 ohnebereich', create=False)
        self.assertContains(response, 'Dieses Tag gibt es nicht: transport:9, ohnebereich.')
        self.assertEqual(self.tags_of(self.crate), [])
        self.assertEqual(Tag.objects.count(), 1)
        # foreign addresses are not accepted as a return target
        response = self.bulk([self.crate], 'eva:40c3', next='https://evil.example.org/')
        self.assertEqual(response.redirect_chain, [(reverse('crates:list'), 302)])
        self.assertEqual(self.tags_of(self.crate), ['eva:40c3'])
        self.assertEqual(self.client.get(reverse('crates:bulk-tag')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('crates:bulk-tag'), {'c': ['0002'], 'tags': 'eva:40c3'}).status_code, 302)
        self.assertEqual(self.tags_of(self.other_crate), [])

    def test_packlist_for_a_filter_or_for_picked_crates(self):
        url = reverse('crates:packlist')
        self.bulk([self.crate, self.other_crate], 'eva:40c3')
        self.bulk([self.crate], 'transport:1')
        response = self.client.get(url, {'tag': 'eva:40c3'})
        self.assertEqual(response.context['crates'], [self.crate, self.other_crate])
        self.assertContains(response, '<h1>Packliste eva:40c3</h1>')
        self.assertContains(response, 'Kabelkiste')
        self.assertContains(response, 'href="/?tag=eva%3A40c3"')
        self.assertContains(response, 'href="?tag=eva%3A40c3&amp;format=csv"')
        self.assertEqual(self.client.get(url, {'tag': ['eva:40c3', 'transport:1']}).context['crates'], [self.crate])
        # checked crates from the print bar
        response = self.client.get(reverse('crates:print'), {'what': 'packlist', 'c': [self.other_crate.code], 'copies': '2'}, follow=True)
        self.assertEqual(response.context['crates'], [self.other_crate])
        self.assertContains(response, '<h1>Packliste</h1>')
        self.assertContains(self.client.get(reverse('crates:list'), {'tag': 'eva:40c3'}), f'href="{url}?tag=eva%3A40c3"')

    @override_settings(PUBLIC_BASE_URL='https://crates.c-base.org')
    def test_packlist_as_csv(self):
        self.bulk([self.crate, self.other_crate], 'eva:40c3 transport:1')
        self.crate.name, self.crate.needs_attention, self.crate.attention_note = '=SUMME(A1)', True, 'zu; voll'
        self.crate.save()
        response = self.client.get(reverse('crates:packlist'), {'tag': 'eva:40c3', 'format': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('filename="crates-eva-40c3.csv"', response['Content-Disposition'])
        text = response.content.decode('utf-8')
        self.assertTrue(text.startswith('\ufeffID;Bezeichnung;'))
        rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], [
            '0001', "'=SUMME(A1)", '600 × 400 mm', '', '', 'alice', '', 'eva:40c3 transport:1',
            'ja', 'zu; voll', '1', 'https://crates.c-base.org/0001',
        ])
        self.assertEqual(rows[2][5:9], ['bob', '', 'eva:40c3 transport:1', ''])
        response = self.client.get(reverse('crates:print'), {'what': 'packlist-csv', 'c': ['0002']}, follow=True)
        self.assertIn('filename="crates-liste.csv"', response['Content-Disposition'])

    @override_settings(PUBLIC_BASE_URL='https://crates.c-base.org')
    def test_packlist_as_markdown(self):
        self.bulk([self.crate, self.other_crate], 'eva:40c3')
        self.crate.name, self.crate.height_mm = 'Kabel *2* [neu]', 220
        self.crate.needs_attention, self.crate.attention_note = True, 'Deckel fehlt\nund zu voll'
        self.crate.save()
        response = self.client.get(reverse('crates:packlist'), {'tag': 'eva:40c3', 'format': 'md'})
        self.assertEqual(response['Content-Type'], 'text/markdown; charset=utf-8')
        self.assertIn('filename="crates-eva-40c3.md"', response['Content-Disposition'])
        lines = response.content.decode('utf-8').splitlines()
        self.assertEqual(lines[0], '# Packliste eva:40c3')
        self.assertRegex(lines[2], r'^2 Crates · Stand \d\d\.\d\d\.\d{4}$')
        self.assertEqual(lines[4:], [
            '- [ ] **[0001](https://crates.c-base.org/0001)** Kabel \\*2\\* \\[neu\\] – 600 × 400 mm, 220 mm hoch · alice · `eva:40c3`',
            '  - ⚠ Needs attention: Deckel fehlt und zu voll',
            '- [ ] **[0002](https://crates.c-base.org/0002)** Werkzeug – 600 × 400 mm · bob · `eva:40c3`',
        ])
        self.assertContains(self.client.get(reverse('crates:packlist'), {'tag': 'eva:40c3'}), 'href="?tag=eva%3A40c3&amp;format=md"')
        response = self.client.get(reverse('crates:print'), {'what': 'packlist-md', 'c': ['0002']}, follow=True)
        self.assertIn('filename="crates-liste.md"', response['Content-Disposition'])

    def test_dev_null_belongs_to_unbecannt(self):
        self.assertEqual([str(member) for member in Crate.objects.get(code='0000').responsible.all()], ['unbecannt'])

    def test_needs_attention_is_set_in_the_form_shown_and_filterable(self):
        other = Crate.objects.create(name='Unauffällig')
        self.assertNotContains(self.client.get(self.crate.get_absolute_url()), 'class="attention"')
        data = {'name': self.crate.name, 'size': self.crate.size, 'needs_attention': 'on'}
        self.client.post(reverse('crates:update', args=[self.crate.code]), data)
        self.crate.refresh_from_db()
        self.assertTrue(self.crate.needs_attention)
        self.assertContains(self.client.get(self.crate.get_absolute_url()), 'class="attention"')
        response = self.client.get(reverse('crates:list'))
        self.assertContains(response, 'class="attention', count=1)
        self.assertIn(other, response.context['object_list'])
        response = self.client.get(reverse('crates:list'), {'attention': '1'})
        self.assertEqual(list(response.context['object_list']), [self.crate])
        # without the checkbox in the form the flag is gone again
        del data['needs_attention']
        self.client.post(reverse('crates:update', args=[self.crate.code]), data)
        self.crate.refresh_from_db()
        self.assertFalse(self.crate.needs_attention)

    def test_attention_note_says_what_the_problem_is_and_goes_away_with_the_flag(self):
        url = reverse('crates:update', args=[self.crate.code])
        data = {'name': self.crate.name, 'size': self.crate.size, 'attention_note': 'Deckel geht nicht mehr zu'}
        self.client.post(url, {**data, 'needs_attention': 'on'})
        self.crate.refresh_from_db()
        self.assertEqual(self.crate.attention_note, 'Deckel geht nicht mehr zu')
        self.assertContains(self.client.get(self.crate.get_absolute_url()), 'Deckel geht nicht mehr zu')
        self.assertContains(self.client.get(reverse('crates:list')), 'Deckel geht nicht mehr zu')
        # the search also finds the crate by its note
        response = self.client.get(reverse('crates:list'), {'q': 'deckel'})
        self.assertEqual(list(response.context['object_list']), [self.crate])
        # without the checkbox no note remains
        self.client.post(url, data)
        self.crate.refresh_from_db()
        self.assertEqual(self.crate.attention_note, '')
        self.assertNotContains(self.client.get(self.crate.get_absolute_url()), 'Deckel geht nicht mehr zu')

    def test_add_edit_and_remove_item(self):
        self.client.post(reverse('crates:item-create', args=[self.crate.code]), {'name': 'Netzteil', 'quantity': 2})
        item = self.crate.items.get(name='Netzteil')
        self.client.post(reverse('crates:item-update', args=[item.pk]), {'name': 'Netzteil', 'quantity': 3})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)
        self.client.post(reverse('crates:item-delete', args=[item.pk]))
        self.assertFalse(self.crate.items.filter(name='Netzteil').exists())

    def test_delete_crate(self):
        self.client.post(reverse('crates:delete', args=[self.other_crate.code]))
        self.assertFalse(Crate.objects.filter(pk=self.other_crate.pk).exists())

    @override_settings(PUBLIC_BASE_URL='https://crates.example.org')
    def test_public_url_uses_configured_base(self):
        self.assertEqual(public_url(self.crate), f'https://crates.example.org/{self.crate.code}')
        self.assertContains(self.client.get(self.crate.get_absolute_url()), public_url(self.crate))

    @override_settings(PUBLIC_BASE_URL='https://crates.c-base.org')
    def test_detail_offers_the_qr_code_link_for_copying(self):
        response = self.client.get(self.crate.get_absolute_url())
        self.assertContains(response, f'id="copy-link" data-link="https://crates.c-base.org/{self.crate.code}"')

    def test_detail_offers_the_ql_print_file_of_the_list(self):
        response = self.client.get(self.crate.get_absolute_url())
        link = f'{reverse("crates:labels")}?c={self.crate.code}&amp;format=ql'
        self.assertContains(response, f'href="{link}"')
        download = self.client.get(link.replace('&amp;', '&'))
        self.assertIn(f'attachment; filename="crate-{self.crate.code}-ql700.bin"', download['Content-Disposition'])

    def test_label_is_landscape_png_in_tape_width(self):
        response = self.client.get(reverse('crates:label', args=[self.crate.code]))
        self.assertEqual(response['Content-Type'], 'image/png')
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.width, 696)
        self.assertLess(image.height, image.width)
        self.assertEqual(image.mode, '1')

    def test_label_pdf_is_one_page_in_tape_width(self):
        response = self.client.get(reverse('crates:label-pdf', args=[self.crate.code]), {'download': '1'})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('crate-0001.pdf', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(response.content.count(b'/Type /Page\n'), 1)
        # 62 mm = 175.7 pt wide; 33 mm = 93.6 pt long: label (26.5 mm) plus a good
        # 3 mm margin at top and bottom that the printer cannot print on
        self.assertRegex(response.content, rb'/MediaBox \[ 0 0 175\.\d+ 93\.\d+ \]')

    def test_label_does_not_depend_on_changeable_crate_data(self):
        before = self.client.get(reverse('crates:label', args=[self.crate.code])).content
        self.crate.name = 'Umbenannt'
        self.crate.save()
        Item.objects.create(crate=self.crate, name='Neu')
        self.assertEqual(before, self.client.get(reverse('crates:label', args=[self.crate.code])).content)

    def test_label_fits_narrow_tape(self):
        image = render_label('https://crates.example.org/001A', '001A', tape_px=306)
        self.assertEqual(image.width, 306)

    def test_label_length_is_the_same_for_every_number(self):
        sizes = {render_label(f'https://crates.example.org/{code}', code).size for code in ['0000', '1111', 'FFFF', '8B3D']}
        self.assertEqual(len(sizes), 1)

    def test_every_label_font_fits_the_tape_with_margins(self):
        for font in FONTS:
            with self.subTest(font=font):
                image = render_label('https://crates.example.org/0000', '0000', font=font)
                left, top, right, bottom = ImageOps.invert(image.convert('L')).getbbox()
                self.assertEqual(image.width, 696)
                self.assertGreater(top, 5)
                self.assertGreater(left, 5)
                # Fonts round to whole pixels, hence two pixels of slack.
                self.assertLessEqual(bottom, image.height - top + 2)
                self.assertLess(right, image.width - 5)

    def test_font_can_be_chosen_per_request(self):
        url = reverse('crates:label', args=[self.crate.code])
        default = self.client.get(url).content
        self.assertNotEqual(default, self.client.get(url, {'font': 'anybody'}).content)
        self.assertNotEqual(default, self.client.get(url, {'font': 'orbitron'}).content)
        self.assertEqual(default, self.client.get(url, {'font': 'gibtsnicht'}).content)

    def test_nfc_logo_sits_below_the_qr_code_and_can_be_switched_off(self):
        url = 'https://crates.c-base.org/10F0'
        with_logo = render_label(url, '10F0')
        without = render_label(url, '10F0', nfc=False)
        self.assertEqual(with_logo.width, without.width)
        # Bottom left, below the QR code, there is something with the logo and nothing without …
        def ink(image, box):
            return sum(ImageOps.invert(image.convert('L')).crop(box).tobytes())
        lower_left = lambda image: (0, int(image.height * 0.78), int(image.width * 0.33), image.height)
        self.assertGreater(ink(with_logo, lower_left(with_logo)), 0)
        with override_settings(LABEL_NFC_LOGO=False):
            self.assertEqual(render_label(url, '10F0').tobytes(), without.tobytes())
        # … and the logo is as wide as the QR code.
        logo = nfc_logo(200)
        self.assertEqual(logo.width, 200)
        self.assertLess(logo.height, 80)

    def test_default_label_sets_the_number_in_orbitron(self):
        from .labels import _Typeface
        face = _Typeface('baijamjuree')
        self.assertEqual(face.spec['file'], 'BaiJamjuree-Bold.ttf')
        self.assertEqual(face.code_face.spec['file'], 'Orbitron.ttf')
        self.assertIs(_Typeface('orbitron').code_face.spec, _Typeface('orbitron').spec)


def photo_upload(size=(3000, 2000), name='IMG_0001.jpg', orientation=None):
    image = Image.new('RGB', size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = 'Geheime Kamera'
    if orientation:
        exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', exif=exif)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


@override_settings(PRINT_COPIES=1)
class PhotoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user('alice', password='pw')
        cls.crate = Crate.objects.create(name='Kabelkiste')

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.media = Path(media.name)
        settings = override_settings(MEDIA_ROOT=self.media)
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(self.member)
        self.upload_url = reverse('crates:photo-upload', args=[self.crate.code])

    def files(self):
        return [path for path in self.media.rglob('*') if path.is_file()]

    def test_upload_stores_a_shrunk_photo_and_shows_it_on_the_crate(self):
        response = self.client.post(self.upload_url, {'images': photo_upload()})
        self.assertRedirects(response, f'/{self.crate.code}#fotos', fetch_redirect_response=False)
        photo = self.crate.photos.get()
        self.assertEqual(photo.uploaded_by, self.member)
        with Image.open(photo.image.path) as image:
            self.assertEqual(image.size, (1600, 1067))
        with Image.open(photo.thumbnail.path) as image:
            self.assertEqual(max(image.size), 400)
        page = self.client.get(self.crate.get_absolute_url())
        self.assertContains(page, reverse('crates:photo-thumbnail', args=[self.crate.code, photo.pk]))
        self.assertContains(page, reverse('crates:photo', args=[self.crate.code, photo.pk]))

    def test_several_photos_in_one_upload(self):
        self.client.post(self.upload_url, {'images': [photo_upload(name='a.jpg'), photo_upload(name='b.jpg')]})
        self.assertEqual(self.crate.photos.count(), 2)

    def test_metadata_is_removed_and_the_file_name_is_not_kept(self):
        self.client.post(self.upload_url, {'images': photo_upload(name='Mein Wohnzimmer.jpg')})
        photo = self.crate.photos.get()
        self.assertNotIn('Wohnzimmer', photo.image.name)
        with Image.open(photo.image.path) as image:
            self.assertEqual(len(image.getexif()), 0)

    def test_photo_taken_upright_is_stored_upright(self):
        # Orientation 6: the phone stores landscape and records the rotation only in EXIF.
        self.client.post(self.upload_url, {'images': photo_upload(size=(800, 600), orientation=6)})
        with Image.open(self.crate.photos.get().image.path) as image:
            self.assertEqual(image.size, (600, 800))

    def test_png_with_transparency_becomes_jpeg(self):
        buffer = io.BytesIO()
        Image.new('RGBA', (100, 100), (0, 0, 0, 0)).save(buffer, format='PNG')
        self.client.post(self.upload_url, {'images': SimpleUploadedFile('a.png', buffer.getvalue())})
        with Image.open(self.crate.photos.get().image.path) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.getpixel((50, 50)), (255, 255, 255))

    def test_file_that_is_no_image_is_rejected_with_a_message(self):
        upload = SimpleUploadedFile('notizen.jpg', b'kein bild')
        response = self.client.post(self.upload_url, {'images': upload}, follow=True)
        self.assertContains(response, 'notizen.jpg')
        self.assertFalse(Photo.objects.exists())
        self.assertEqual(self.files(), [])

    def test_upload_without_file_shows_a_message(self):
        response = self.client.post(self.upload_url, follow=True)
        self.assertContains(response, 'kein Bild ausgewählt')

    def test_photos_are_only_served_to_logged_in_members(self):
        self.client.post(self.upload_url, {'images': photo_upload()})
        photo = self.crate.photos.get()
        for name in ('crates:photo', 'crates:photo-thumbnail'):
            response = self.client.get(reverse(name, args=[self.crate.code, photo.pk]))
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            Image.open(io.BytesIO(b''.join(response.streaming_content))).verify()
        self.client.logout()
        response = self.client.get(reverse('crates:photo', args=[self.crate.code, photo.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertEqual(self.client.post(self.upload_url, {'images': photo_upload()}).status_code, 302)
        self.assertEqual(self.crate.photos.count(), 1)

    def test_deleting_a_photo_removes_its_files(self):
        self.client.post(self.upload_url, {'images': photo_upload()})
        self.assertEqual(len(self.files()), 2)
        response = self.client.post(reverse('crates:photo-delete', args=[self.crate.code, self.crate.photos.get().pk]))
        self.assertRedirects(response, f'/{self.crate.code}#fotos', fetch_redirect_response=False)
        self.assertFalse(Photo.objects.exists())
        self.assertEqual(self.files(), [])

    def test_deleting_the_crate_removes_its_photo_files(self):
        self.client.post(self.upload_url, {'images': photo_upload()})
        self.crate.delete()
        self.assertEqual(self.files(), [])

    def test_missing_file_is_404(self):
        self.client.post(self.upload_url, {'images': photo_upload()})
        photo = self.crate.photos.get()
        Path(photo.image.path).unlink()
        self.assertEqual(self.client.get(reverse('crates:photo', args=[self.crate.code, photo.pk])).status_code, 404)

    def test_unknown_crate_is_404(self):
        self.assertEqual(self.client.post('/0FFF/pics/', {'images': photo_upload()}).status_code, 404)

    def test_card_shows_details_content_and_at_most_four_photos(self):
        Item.objects.create(crate=self.crate, name='HDMI-Kabel', quantity=4)
        for _ in range(5):
            self.client.post(self.upload_url, {'images': photo_upload(size=(200, 100))})
        response = self.client.get(reverse('crates:card', args=[self.crate.code]))
        self.assertContains(response, 'Kabelkiste')
        self.assertContains(response, 'HDMI-Kabel')
        self.assertContains(response, reverse('crates:label', args=[self.crate.code]))
        self.assertContains(response, '<body class="a5">')
        self.assertEqual(len(response.context['cards'][0]['photos']), 4)
        newest = self.crate.photos.first()
        self.assertContains(response, reverse('crates:photo', args=[self.crate.code, newest.pk]))

    def test_card_format_can_be_chosen_and_falls_back_to_a5(self):
        url = reverse('crates:card', args=[self.crate.code])
        self.assertContains(self.client.get(url, {'format': 'a6'}), '<body class="a6">')
        self.assertContains(self.client.get(url, {'format': 'a0'}), '<body class="a5">')

    def test_card_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('crates:card', args=[self.crate.code])).status_code, 302)

    def test_a5_prints_on_portrait_a4_and_a6_on_landscape(self):
        url = reverse('crates:card', args=[self.crate.code])
        self.assertContains(self.client.get(url), 'size: A4 portrait')
        self.assertContains(self.client.get(url, {'format': 'a6'}), 'size: A4 landscape')

    def test_several_crates_share_sheets_two_per_a5_and_four_per_a6(self):
        codes = [self.crate.code] + [Crate.objects.create(name=f'Kiste {n}').code for n in range(4)]
        url = reverse('crates:cards')
        a5 = self.client.get(url, {'c': codes, 'format': 'a5'})
        self.assertEqual([len(sheet) for sheet in a5.context['sheets']], [2, 2, 1])
        a6 = self.client.get(url, {'c': codes, 'format': 'a6'})
        self.assertEqual([len(sheet) for sheet in a6.context['sheets']], [4, 1])
        self.assertContains(a6, 'Kiste 3')
        self.assertContains(a6, 'class="sheet"', count=2)
        # the switch keeps the selection
        self.assertContains(a6, f'c={codes[0]}&amp;c={codes[1]}')

    def test_card_sheet_ignores_unknown_codes_and_needs_a_selection(self):
        url = reverse('crates:cards')
        response = self.client.get(url, {'c': [self.crate.code.lower(), 'FFFE', 'unsinn']})
        self.assertEqual(len(response.context['cards']), 1)
        response = self.client.get(url, follow=True)
        self.assertRedirects(response, reverse('crates:list'))
        self.assertContains(response, 'mindestens eine Crate')

    def test_list_offers_selection_for_card_printing(self):
        response = self.client.get(reverse('crates:list'))
        self.assertContains(response, f'name="c" value="{self.crate.code}"')
        self.assertContains(response, f'action="{reverse("crates:print")}"')
        self.assertContains(response, '<option value="cards-a6">')

    def test_photo_address_and_file_name_carry_the_crate_id(self):
        self.client.post(self.upload_url, {'images': photo_upload(size=(200, 100))})
        photo = self.crate.photos.get()
        response = self.client.get(f'/{self.crate.code}/pic/{photo.pk}.jpg')
        self.assertEqual(response['Content-Disposition'], f'inline; filename="{self.crate.code}-{photo.pk}.jpg"')

    def test_photo_under_the_wrong_crate_is_404_and_cannot_be_deleted_there(self):
        self.client.post(self.upload_url, {'images': photo_upload(size=(200, 100))})
        photo = self.crate.photos.get()
        other = Crate.objects.create(name='Andere')
        self.assertEqual(self.client.get(reverse('crates:photo', args=[other.code, photo.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('crates:photo-delete', args=[other.code, photo.pk])).status_code, 404)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_new_pictures_and_cards_have_english_paths(self):
        self.assertEqual(reverse('crates:create'), '/new/')
        self.assertEqual(reverse('crates:cards'), '/cards/')
        self.assertEqual(reverse('crates:photo', args=['10F0', 7]), '/10F0/pic/7.jpg')
        self.assertEqual(reverse('crates:photo-thumbnail', args=['10F0', 7]), '/10F0/pic/7-thumb.jpg')


class AddressTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('alice'))
        self.crate = Crate.objects.create(name='Kabelkiste', code='10F0')

    def test_crate_lives_directly_under_the_host_without_trailing_slash(self):
        self.assertEqual(self.crate.get_absolute_url(), '/10F0')
        self.assertContains(self.client.get('/10F0'), 'Kabelkiste')

    def test_old_prefix_and_trailing_slash_redirect_to_the_short_address(self):
        for old in ('/c/10F0/', '/10F0/'):
            self.assertRedirects(self.client.get(old), '/10F0', status_code=301)

    def test_hex_looking_words_do_not_shadow_fixed_pages(self):
        for name in ('crates:create', 'crates:cards'):
            self.assertNotEqual(self.client.get(reverse(name), {'c': '10F0'}).status_code, 404)
        # a word made of hex characters, however, is a crate ID
        self.assertEqual(self.client.get('/cafe').status_code, 404)
        Crate.objects.create(name='Kaffee', code='CAFE')
        self.assertContains(self.client.get('/cafe'), 'Kaffee')


@override_settings(PUBLIC_BASE_URL='https://crates.c-base.org', LABEL_FONT='baijamjuree', LABEL_WIDTH_PX=696, PRINT_COPIES=1)
class LabelSheetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user('alice')
        cls.codes = [Crate.objects.create(name=f'Kiste {n}').code for n in range(3)]

    def setUp(self):
        self.client.force_login(self.member)
        self.url = reverse('crates:labels')

    def test_pdf_has_one_page_per_selected_crate(self):
        response = self.client.get(self.url, {'c': self.codes, 'format': 'pdf'})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('crates-0001-0003-labels.pdf', response['Content-Disposition'])
        self.assertEqual(response.content.count(b'/Type /Page\n'), 3)

    def test_ql_file_carries_every_label_with_a_cut_after_each(self):
        labels = [(f'https://crates.c-base.org/{code}', code) for code in self.codes]
        data = labels_ql_raster(labels)
        height = render_label(*labels[0]).height
        self.assertEqual(data[:202], b'\x00' * 200 + b'\x1b\x40')
        page = 13 + 4 + 4 + 4 + 5 + height * 93 + 1
        self.assertEqual(len(data), 202 + 3 * page)
        for index in range(3):
            block = data[202 + index * page:202 + (index + 1) * page]
            # continuous tape 62 mm, number of lines, first page / following page
            self.assertEqual(block[:13], b'\x1b\x69\x7a\xce\x0a\x3e\x00' + height.to_bytes(4, 'little') + bytes([min(index, 1), 0]))
            # cut automatically, after every label, also after the last one
            self.assertEqual(block[13:25], b'\x1b\x69\x4d\x40' + b'\x1b\x69\x41\x01' + b'\x1b\x69\x4b\x08')
            self.assertEqual(block[30:33], b'\x67\x00\x5a')
            self.assertEqual(block[-1:], b'\x1a')

    def test_ql_raster_is_the_mirrored_label_inside_the_print_head(self):
        url, code = 'https://crates.c-base.org/0001', '0001'
        label = render_label(url, code)
        data = labels_ql_raster([(url, code)])
        start = 202 + 30
        rows = b''.join(data[start + row * 93 + 3:start + (row + 1) * 93] for row in range(label.height))
        printed = Image.frombytes('1', (720, label.height), rows)
        expected = Image.new('1', (720, label.height), 0)
        inverted = ImageOps.invert(label.convert('L')).convert('1')
        expected.paste(inverted.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (12, 0))
        self.assertEqual(printed.tobytes(), expected.tobytes())
        self.assertGreater(sum(printed.convert('L').tobytes()), 0)

    def test_ql_download_and_missing_selection(self):
        response = self.client.get(self.url, {'c': self.codes[:1], 'format': 'ql'})
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment; filename="crate-0001-ql700.bin"', response['Content-Disposition'])
        self.assertEqual(response.content, labels_ql_raster([('https://crates.c-base.org/0001', '0001')]))
        self.assertRedirects(self.client.get(self.url), reverse('crates:list'))

    @override_settings(LABEL_WIDTH_PX=500)
    def test_ql_file_needs_a_known_tape_width(self):
        response = self.client.get(self.url, {'c': self.codes, 'format': 'ql'}, follow=True)
        self.assertContains(response, 'Keine QL-Rolle')

    def test_list_offers_label_printing_for_the_selection(self):
        response = self.client.get(reverse('crates:list'))
        self.assertContains(response, '<option value="labels-pdf">')
        self.assertContains(response, '<option value="labels-ql">')

    def test_print_bar_leads_to_the_chosen_variant_and_keeps_selection_and_copies(self):
        url = reverse('crates:print')
        query = {'c': self.codes[:2], 'copies': '3'}
        targets = {
            'labels-pdf': '/labels/?copies=3&c=0001&c=0002&format=pdf',
            'labels-ql': '/labels/?copies=3&c=0001&c=0002&format=ql',
            'cards-a5': '/cards/?copies=3&c=0001&c=0002&format=a5',
            'cards-a6': '/cards/?copies=3&c=0001&c=0002&format=a6',
            'unsinn': '/labels/?copies=3&c=0001&c=0002&format=pdf',
        }
        for what, target in targets.items():
            response = self.client.get(url, {**query, 'what': what})
            self.assertEqual(response.status_code, 302)
            self.assertCountEqual(response['Location'].split('?')[1].split('&'), target.split('?')[1].split('&'))
            self.assertEqual(response['Location'].split('?')[0], target.split('?')[0])

    def test_labels_require_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url, {'c': self.codes}).status_code, 302)


@override_settings(PUBLIC_BASE_URL='https://crates.c-base.org', LABEL_FONT='baijamjuree', LABEL_WIDTH_PX=696, PRINT_COPIES=2)
class CopiesTests(TestCase):
    """As a rule every label and every card is needed twice."""

    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user('alice')
        cls.codes = [Crate.objects.create(name=f'Kiste {n}').code for n in range(3)]

    def setUp(self):
        self.client.force_login(self.member)

    def pages(self, response):
        return response.content.count(b'/Type /Page\n')

    def test_labels_come_twice_by_default_and_as_often_as_asked(self):
        url = reverse('crates:labels')
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes})), 6)
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes, 'copies': '1'})), 3)
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes, 'copies': '3'})), 9)
        self.assertEqual(self.pages(self.client.get(reverse('crates:label-pdf', args=['0001']))), 2)

    def test_copies_of_a_label_follow_each_other_in_the_ql_file(self):
        response = self.client.get(reverse('crates:labels'), {'c': self.codes[:2], 'format': 'ql'})
        expected = labels_ql_raster([(f'https://crates.c-base.org/{code}', code) for code in ['0001', '0001', '0002', '0002']])
        self.assertEqual(response.content, expected)

    def test_cards_come_twice_so_one_a5_sheet_holds_both_copies(self):
        response = self.client.get(reverse('crates:cards'), {'c': self.codes, 'format': 'a5'})
        sheets = [[card['crate'].code for card in sheet] for sheet in response.context['sheets']]
        self.assertEqual(sheets, [['0001', '0001'], ['0002', '0002'], ['0003', '0003']])
        a6 = self.client.get(reverse('crates:cards'), {'c': self.codes, 'format': 'a6', 'copies': '2'})
        self.assertEqual([len(sheet) for sheet in a6.context['sheets']], [4, 2])
        single = self.client.get(reverse('crates:card', args=['0001']))
        self.assertEqual(len(single.context['cards']), 2)
        self.assertContains(single, '<title>Karte 0001')

    def test_number_of_copies_is_limited_and_nonsense_falls_back_to_the_default(self):
        url = reverse('crates:labels')
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes[:1], 'copies': '999'})), 10)
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes[:1], 'copies': '0'})), 1)
        self.assertEqual(self.pages(self.client.get(url, {'c': self.codes[:1], 'copies': 'viele'})), 2)

    def test_card_page_keeps_selection_when_switching_copies_or_format(self):
        response = self.client.get(reverse('crates:cards'), {'c': self.codes[:2], 'format': 'a6', 'copies': '3'})
        self.assertContains(response, 'c=0001&amp;c=0002&amp;format=a6&amp;copies=1')
        self.assertContains(response, 'c=0001&amp;c=0002&amp;copies=3&amp;format=a5')

    def test_list_and_crate_page_offer_the_default_number_of_copies(self):
        self.assertContains(self.client.get(reverse('crates:list')), 'name="copies" value="2"')
        page = self.client.get('/0001')
        self.assertContains(page, 'Label als PDF (2×)')
        self.assertContains(page, 'Karte DIN A5 (2×)')


class AppInstallTests(TestCase):
    """Installing on the phone as an app (PWA)."""

    def test_manifest_is_public_and_points_to_existing_icons(self):
        from django.contrib.staticfiles import finders

        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        data = response.json()
        self.assertEqual((data['start_url'], data['scope'], data['display']), ('/', '/', 'standalone'))
        self.assertEqual({icon['sizes'] for icon in data['icons']}, {'192x192', '512x512'})
        self.assertIn('maskable', [icon['purpose'] for icon in data['icons']])
        for icon in data['icons']:
            path = finders.find(icon['src'].removeprefix('/static/'))
            self.assertIsNotNone(path, icon['src'])
            with Image.open(path) as image:
                self.assertEqual(f'{image.width}x{image.height}', icon['sizes'])

    def test_pages_link_the_manifest(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, '<link rel="manifest" href="/manifest.webmanifest">')
        self.assertContains(response, 'apple-touch-icon')


class ThemeTests(TestCase):
    """The switchable colour variant "amber" in the navigation."""

    def test_every_page_offers_the_switch_with_and_without_login(self):
        login = self.client.get(reverse('login'))
        self.client.force_login(get_user_model().objects.create_user('alice'))
        for response in (login, self.client.get(reverse('crates:list'))):
            self.assertContains(response, 'data-cbase-theme-toggle', count=1)
            for file in ('c-base-bootstrap/css/c-base-amber.css', 'crates/theme-amber.css', 'c-base-bootstrap/js/c-base-theme.js'):
                self.assertContains(response, f'/static/{file}"')

    def test_theme_files_and_the_font_are_served_as_static_files(self):
        from django.contrib.staticfiles import finders

        for file in ('css/c-base-amber.css', 'js/c-base-theme.js', 'fonts/Orbitron.ttf'):
            self.assertIsNotNone(finders.find(f'c-base-bootstrap/{file}'), file)
        self.assertIsNotNone(finders.find('crates/theme-amber.css'))


@override_settings(
    PUBLIC_BASE_URL='https://crates.c-base.org', MAIL_ENABLED=True, REMINDER_INTERVAL_DAYS=7,
    MEMBER_EMAIL_DOMAIN='c-base.org', DEFAULT_FROM_EMAIL='crates@c-base.org',
)
class ReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.manager = users.create_user('mona', first_name='Mona', email='mona@example.org')
        cls.manager.groups.add(Group.objects.get(name='Manager'))
        cls.alice = users.create_user('alice', first_name='Alice', last_name='Liddell', email='alice@example.org')
        cls.bob = users.create_user('bob')
        cls.unknown = get_user_model().unknown()

        def crate(name, *members, **fields):
            crate = Crate.objects.create(name=name, **fields)
            crate.responsible.set(members)
            return crate

        cls.lid = crate('Kabel', cls.alice, needs_attention=True, attention_note='Deckel geht nicht zu\nzu voll')
        cls.shared = crate('Werkzeug', cls.alice, cls.bob, needs_attention=True)
        cls.orphan = crate('Fundsachen', cls.unknown, needs_attention=True, attention_note='stinkt')
        cls.fine = crate('Ordentlich', cls.bob)
        cls.url = reverse('crates:remind')

    def setUp(self):
        self.client.force_login(self.manager)

    def test_only_managers_and_superusers_may_remind(self):
        self.assertContains(self.client.get(reverse('crates:list')), self.url)
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse('crates:list')), self.url)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(mail.outbox, [])
        self.client.force_login(get_user_model().objects.create_superuser('root'))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_preview_lists_who_gets_which_crates_and_sends_nothing(self):
        response = self.client.get(self.url)
        plan = response.context['plan']
        self.assertEqual(
            [(reminder.address, [crate.code for crate in reminder.crates]) for reminder in plan.reminders],
            [('alice@example.org', [self.lid.code, self.shared.code]), ('bob@c-base.org', [self.shared.code])],
        )
        self.assertEqual(plan.unreachable, [self.orphan])
        self.assertContains(response, '2 Mails verschicken')
        self.assertEqual(mail.outbox, [])

    def test_one_mail_per_person_with_note_and_link(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, f"{reverse('crates:list')}?attention=1")
        self.assertEqual([message.to for message in mail.outbox], [['alice@example.org'], ['bob@c-base.org']])
        to_alice, to_bob = mail.outbox
        self.assertEqual(to_alice.subject, '2 deiner c-base cargo crates brauchen Aufmerksamkeit')
        self.assertEqual(to_alice.reply_to, ['mona@example.org'])
        self.assertEqual(to_alice.from_email, 'crates@c-base.org')
        self.assertIn('Hallo Alice,', to_alice.body)
        self.assertIn(f'  {self.lid.code} Kabel\n  Deckel geht nicht zu\n  zu voll\n  https://crates.c-base.org/{self.lid.code}', to_alice.body)
        self.assertIn(f'  {self.shared.code} Werkzeug\n  (ohne Bemerkung)\n', to_alice.body)
        self.assertEqual(to_bob.subject, f'c-base cargo crate {self.shared.code} braucht Aufmerksamkeit')
        self.assertIn('Hallo bob,', to_bob.body)
        self.assertNotIn('Kabel', to_bob.body)
        for message in mail.outbox:
            self.assertNotIn('Fundsachen', message.body)
            self.assertNotIn('Ordentlich', message.body)

    def test_reminded_crates_get_no_second_mail_until_the_interval_is_over(self):
        self.client.post(self.url)
        self.lid.refresh_from_db()
        self.orphan.refresh_from_db()
        self.assertIsNotNone(self.lid.attention_reminded_at)
        self.assertIsNone(self.orphan.attention_reminded_at)
        self.assertContains(self.client.get(self.lid.get_absolute_url()), 'zuletzt per Mail erinnert')
        mail.outbox.clear()
        response = self.client.get(self.url)
        self.assertEqual(response.context['plan'].reminders, [])
        self.assertEqual(response.context['plan'].recent, [self.lid, self.shared])
        self.client.post(self.url)
        self.assertEqual(mail.outbox, [])
        # once the waiting period is over it works again
        Crate.objects.filter(pk=self.lid.pk).update(attention_reminded_at=timezone.now() - timedelta(days=8))
        self.client.post(self.url)
        self.assertEqual([message.to for message in mail.outbox], [['alice@example.org']])
        self.assertNotIn('Werkzeug', mail.outbox[0].body)

    def test_a_new_problem_on_the_same_crate_may_be_reported_right_away(self):
        self.client.post(self.url)
        self.lid.needs_attention = False
        self.lid.save()
        self.assertIsNone(self.lid.attention_reminded_at)
        self.lid.needs_attention = True
        self.lid.save()
        mail.outbox.clear()
        self.client.post(self.url)
        self.assertEqual([message.to for message in mail.outbox], [['alice@example.org']])

    def test_failed_mail_is_reported_and_its_crates_stay_due(self):
        def send(message, *args, **kwargs):
            if message.to == ['alice@example.org']:
                raise OSError('Postfach kaputt')
            mail.outbox.append(message)
            return 1

        with mock.patch('django.core.mail.EmailMessage.send', send), self.assertLogs('crates.reminders', 'ERROR'):
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'Nicht verschickt werden konnte die Mail an: Alice Liddell.')
        self.assertContains(response, '1 Mail verschickt, zu 1 Crate.')
        self.lid.refresh_from_db()
        self.shared.refresh_from_db()
        self.assertIsNone(self.lid.attention_reminded_at)
        # Bob got his mail about the shared crate
        self.assertIsNotNone(self.shared.attention_reminded_at)

    @override_settings(MAIL_ENABLED=False)
    def test_without_mail_setup_nothing_is_sent_or_marked(self):
        self.assertContains(self.client.get(self.url), 'EMAIL_HOST')
        self.client.post(self.url)
        self.assertEqual(mail.outbox, [])
        self.lid.refresh_from_db()
        self.assertIsNone(self.lid.attention_reminded_at)
