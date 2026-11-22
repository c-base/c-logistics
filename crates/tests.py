from django.contrib.auth import get_user_model
import io
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, ImageOps
from django.urls import reverse

from .labels import FONTS, labels_ql_raster, nfc_logo, public_url, render_label
from .models import Crate, Item, Photo, format_code


# Unabhängig von einer lokalen .env.
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
        response = self.client.post(reverse('crates:create'), {
            'name': 'Lötkram', 'size': '400x300',
            'responsible': [self.member.pk, self.other.pk],
        })
        crate = Crate.objects.get(name='Lötkram')
        self.assertRedirects(response, crate.get_absolute_url())
        self.assertEqual(crate.responsible.count(), 2)

    def test_crate_without_responsible_member_belongs_to_unbecannt(self):
        self.client.post(reverse('crates:create'), {'name': 'Herrenlos', 'size': '400x300'})
        crate = Crate.objects.get(name='Herrenlos')
        self.assertEqual([member.username for member in crate.responsible.all()], ['unbecannt'])
        self.assertContains(self.client.get(crate.get_absolute_url()), 'unbecannt')

    def test_unbecannt_goes_away_as_soon_as_a_member_is_responsible(self):
        unknown = get_user_model().unknown()
        data = {'name': 'Gefunden', 'size': '400x300', 'responsible': [unknown.pk, self.member.pk]}
        self.client.post(reverse('crates:create'), data)
        crate = Crate.objects.get(name='Gefunden')
        self.assertEqual(list(crate.responsible.all()), [self.member])
        # … und kommt zurück, wenn der letzte Member herausgenommen wird
        self.client.post(reverse('crates:update', args=[crate.code]), {'name': 'Gefunden', 'size': '400x300'})
        self.assertEqual(list(crate.responsible.all()), [unknown])

    def test_unbecannt_is_a_placeholder_that_cannot_log_in_and_heads_the_list(self):
        unknown = get_user_model().unknown()
        self.assertFalse(unknown.is_active)
        self.assertFalse(unknown.has_usable_password())
        self.assertTrue(unknown.is_unknown)
        self.assertEqual(get_user_model().objects.filter(username='unbecannt').count(), 1)
        response = self.client.get(reverse('crates:create'))
        choices = [str(label) for _, label in response.context['form'].fields['responsible'].choices]
        self.assertEqual(choices[0], 'unbecannt')
        self.assertContains(response, f'data-unknown="{unknown.pk}"')

    def test_dev_null_belongs_to_unbecannt(self):
        self.assertEqual([str(member) for member in Crate.objects.get(code='0000').responsible.all()], ['unbecannt'])

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
        # 62 mm = 175,7 pt breit; 33 mm = 93,6 pt lang: Label (26,5 mm) plus gut
        # 3 mm Rand oben und unten, die der Drucker nicht bedrucken kann
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
                # Schriften runden auf ganze Pixel, deshalb zwei Pixel Spiel.
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
        # Unten links, unter dem QR-Code, steht mit Logo etwas und ohne nichts …
        def ink(image, box):
            return sum(ImageOps.invert(image.convert('L')).crop(box).tobytes())
        lower_left = lambda image: (0, int(image.height * 0.78), int(image.width * 0.33), image.height)
        self.assertGreater(ink(with_logo, lower_left(with_logo)), 0)
        with override_settings(LABEL_NFC_LOGO=False):
            self.assertEqual(render_label(url, '10F0').tobytes(), without.tobytes())
        # … und das Logo ist so breit wie der QR-Code.
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
        # Orientierung 6: das Telefon speichert quer und merkt sich die Drehung nur im EXIF.
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
        # der Umschalter behält die Auswahl
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
        # ein Wort aus Hex-Zeichen ist dagegen eine Crate-ID
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
            # Endlosband 62 mm, Zeilenzahl, erste Seite / Folgeseite
            self.assertEqual(block[:13], b'\x1b\x69\x7a\xce\x0a\x3e\x00' + height.to_bytes(4, 'little') + bytes([min(index, 1), 0]))
            # automatisch schneiden, nach jedem Label, auch nach dem letzten
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
    """In der Regel braucht man jedes Label und jede Karte doppelt."""

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
    """Installation auf dem Telefon als App (PWA)."""

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
