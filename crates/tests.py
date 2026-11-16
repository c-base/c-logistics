from django.contrib.auth import get_user_model
import io

from django.test import TestCase, override_settings
from PIL import Image, ImageOps
from django.urls import reverse

from .labels import FONTS, public_url, render_label
from .models import Crate, Item, format_code


# Unabhängig von einer lokalen .env.
@override_settings(PUBLIC_BASE_URL='', LABEL_FONT='baijamjuree', LABEL_WIDTH_PX=696)
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

    def test_codes_are_sequential_four_digit_hex(self):
        self.assertEqual(self.crate.code, '0001')
        self.assertEqual(self.other_crate.code, '0002')
        self.assertEqual(format_code(26), '001A')
        self.assertEqual(format_code(0xFFFF), 'FFFF')

    def test_0000_is_dev_null_and_never_assigned_to_a_new_crate(self):
        self.assertEqual(Crate.objects.get(code='0000').name, '/dev/null')
        self.assertContains(self.client.get('/c/0000/'), '/dev/null')
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
        self.assertEqual(self.crate.get_absolute_url(), f'/c/{self.crate.code}/')

    def test_scan_requires_login_and_returns_to_crate(self):
        self.client.logout()
        url = self.crate.get_absolute_url()
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_detail_shows_content_and_accepts_short_code(self):
        response = self.client.get('/c/1/')
        self.assertContains(response, 'HDMI-Kabel')
        self.assertContains(response, 'alice')

    def test_unknown_code_is_404(self):
        self.assertEqual(self.client.get('/c/0BAD/').status_code, 404)

    def test_lowercase_code_opens_crate(self):
        crate = Crate.objects.create(name='Hex', code='00AF')
        crate.responsible.add(self.member)
        self.assertContains(self.client.get('/c/00af/'), 'Hex')

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
        response = self.client.post(reverse('crates:create'), {
            'name': 'Lötkram', 'size': '400x300',
            'responsible': [self.member.pk, self.other.pk],
        })
        crate = Crate.objects.get(name='Lötkram')
        self.assertRedirects(response, crate.get_absolute_url())
        self.assertEqual(crate.responsible.count(), 2)

    def test_crate_needs_a_responsible_member(self):
        response = self.client.post(reverse('crates:create'), {'name': 'Herrenlos', 'size': '400x300'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Crate.objects.filter(name='Herrenlos').exists())

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
        self.assertEqual(public_url(self.crate), f'https://crates.example.org/c/{self.crate.code}/')
        self.assertContains(self.client.get(self.crate.get_absolute_url()), public_url(self.crate))

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
        # 62 mm = 175,7 pt
        self.assertRegex(response.content, rb'/MediaBox \[ 0 0 175\.\d+ ')

    def test_label_does_not_depend_on_changeable_crate_data(self):
        before = self.client.get(reverse('crates:label', args=[self.crate.code])).content
        self.crate.name = 'Umbenannt'
        self.crate.save()
        Item.objects.create(crate=self.crate, name='Neu')
        self.assertEqual(before, self.client.get(reverse('crates:label', args=[self.crate.code])).content)

    def test_label_fits_narrow_tape(self):
        image = render_label('https://crates.example.org/c/001A/', '001A', tape_px=306)
        self.assertEqual(image.width, 306)

    def test_label_length_is_the_same_for_every_number(self):
        sizes = {render_label(f'https://crates.example.org/c/{code}/', code).size for code in ['0000', '1111', 'FFFF', '8B3D']}
        self.assertEqual(len(sizes), 1)

    def test_every_label_font_fits_the_tape_with_margins(self):
        for font in FONTS:
            with self.subTest(font=font):
                image = render_label('https://crates.example.org/c/0000/', '0000', font=font)
                left, top, right, bottom = ImageOps.invert(image.convert('L')).getbbox()
                self.assertEqual(image.width, 696)
                self.assertGreater(top, 5)
                self.assertGreater(left, 5)
                # Schriften runden auf ganze Pixel, deshalb zwei Pixel Spiel.
                self.assertLessEqual(bottom, image.height - top + 2)
                self.assertLess(right, image.width - 5)

    def test_font_can_be_chosen_per_request(self):
        url = reverse('crates:label', args=[self.crate.code])
        default = self.client.get(url).content
        self.assertNotEqual(default, self.client.get(url, {'font': 'anybody'}).content)
        self.assertNotEqual(default, self.client.get(url, {'font': 'orbitron'}).content)
        self.assertEqual(default, self.client.get(url, {'font': 'gibtsnicht'}).content)

    def test_default_label_sets_the_number_in_orbitron(self):
        from .labels import _Typeface
        face = _Typeface('baijamjuree')
        self.assertEqual(face.spec['file'], 'BaiJamjuree-Bold.ttf')
        self.assertEqual(face.code_face.spec['file'], 'Orbitron.ttf')
        self.assertIs(_Typeface('orbitron').code_face.spec, _Typeface('orbitron').spec)
