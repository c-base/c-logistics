import re
import uuid

import reversion
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, models, transaction
from django.urls import reverse

CODE_DIGITS = 4
# /dev/null, the bin: created by a migration, never a real crate.
DEV_NULL_CODE = '0000'
MAX_NUMBER = 16 ** CODE_DIGITS - 1


def format_code(number):
    """Sequential number as a four-digit hex ID, e.g. 26 -> '001A'."""
    return f'{number:0{CODE_DIGITS}X}'


def normalize_code(value):
    """Turns input such as '1a' or '001a' into the stored ID '001A'."""
    return value.upper().zfill(CODE_DIGITS)


class Location(models.Model):
    name = models.CharField('Name', max_length=100, unique=True)
    description = models.TextField('Beschreibung', blank=True)

    class Meta:
        verbose_name = 'Lagerort'
        verbose_name_plural = 'Lagerorte'
        ordering = ['name']

    def __str__(self):
        return self.name


class Tag(models.Model):
    """A tag with a scope, written scope:value – e.g. eva:40c3 or transport:1.

    The scope says what it is about (event, transport …), the value which one.
    Tags are a fixed selection: managers create them under "Tags verwalten"
    (or in the admin); on the crates they are only selected.
    """

    PATTERN = re.compile(r'(?P<scope>[\w-]+):(?P<value>[\w.-]+)')

    scope = models.CharField('Bereich', max_length=30)
    value = models.CharField('Wert', max_length=50)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'
        ordering = ['scope', 'value']
        constraints = [models.UniqueConstraint(fields=['scope', 'value'], name='unique_tag')]

    def __str__(self):
        return f'{self.scope}:{self.value}'

    @classmethod
    def parse(cls, text):
        """Splits 'EVA:40c3' into ('eva', '40c3'). Raises ValueError if it is not a tag."""
        match = cls.PATTERN.fullmatch(text.strip().lower())
        if not match:
            raise ValueError(f'„{text}“ ist kein Tag. Tags sehen so aus: bereich:wert, z. B. eva:40c3.')
        scope, value = match['scope'], match['value']
        if len(scope) > 30 or len(value) > 50:
            raise ValueError(f'„{text}“ ist zu lang.')
        return scope, value

    @classmethod
    def parse_many(cls, text):
        """'eva:40c3, Transport:1' becomes [('eva', '40c3'), ('transport', '1')], without duplicates."""
        tags = []
        for word in text.replace(',', ' ').split():
            tag = cls.parse(word)
            if tag not in tags:
                tags.append(tag)
        return tags

    @classmethod
    def find(cls, text):
        """The tag for 'eva:40c3', or None if it does not exist."""
        try:
            scope, value = cls.parse(text)
        except ValueError:
            return None
        return cls.objects.filter(scope=scope, value=value).first()


class Crate(models.Model):
    class Size(models.TextChoices):
        S600X400 = '600x400', '600 × 400 mm'
        S400X300 = '400x300', '400 × 300 mm'
        S300X200 = '300x200', '300 × 200 mm'
        OTHER = 'other', 'Sonstiges'

    code = models.CharField(
        'ID', max_length=CODE_DIGITS, unique=True, editable=False,
        help_text='Fortlaufende Nummer, vierstellig hexadezimal. Steht im NFC-Tag und auf dem Label.',
    )
    name = models.CharField('Bezeichnung', max_length=200)
    description = models.TextField('Beschreibung', blank=True)
    size = models.CharField('Grundmaß', max_length=10, choices=Size.choices, default=Size.S600X400)
    height_mm = models.PositiveIntegerField('Höhe (mm)', null=True, blank=True)
    color = models.CharField('Farbe', max_length=50, blank=True)
    responsible = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name='Verantwortliche', related_name='crates',
    )
    location = models.ForeignKey(
        Location, verbose_name='Lagerort', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='crates',
    )
    tags = models.ManyToManyField(Tag, verbose_name='Tags', blank=True, related_name='crates')
    needs_attention = models.BooleanField(
        'Needs attention', default=False,
        help_text='Hier stimmt etwas nicht, z. B. ist der Inhalt zu groß für die Kiste.',
    )
    attention_note = models.TextField(
        'Was ist das Problem?', blank=True,
        help_text='Bemerkung zu „Needs attention“. Verschwindet, sobald der Haken herausgenommen wird.',
    )
    attention_reminded_at = models.DateTimeField(
        'Verantwortliche zuletzt erinnert', null=True, blank=True, editable=False,
    )
    created_at = models.DateTimeField('Angelegt', auto_now_add=True)
    updated_at = models.DateTimeField('Geändert', auto_now=True)

    class Meta:
        verbose_name = 'Cargo Crate'
        verbose_name_plural = 'c-base cargo crates'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.name}'

    @classmethod
    def next_code(cls):
        last = cls.objects.order_by('-code').values_list('code', flat=True).first()
        number = int(last, 16) + 1 if last else 1
        if number > MAX_NUMBER:
            raise OverflowError('Alle vierstelligen Hex-IDs sind vergeben.')
        return format_code(number)

    def save(self, *args, **kwargs):
        # The note belongs to the flag: once the problem is solved, it is obsolete.
        if not self.needs_attention:
            self.attention_note = ''
            # a new problem on the same crate may be reported again right away
            self.attention_reminded_at = None
        if self.code:
            return super().save(*args, **kwargs)
        # Two crates created at the same time could draw the same number; retry then.
        for attempt in range(5):
            self.code = self.next_code()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.code = ''
                if attempt == 4:
                    raise

    def get_absolute_url(self):
        return reverse('crates:detail', kwargs={'code': self.code})

    @property
    def has_contents(self):
        return self.items.exists() or self.photos.exists()

    # What makes up the contents and changes boxes on a move. ID, size, height
    # and colour belong to the box itself and stay where they are.
    CONTENT_FIELDS = ('name', 'description', 'location', 'needs_attention', 'attention_note', 'attention_reminded_at')

    def swap_contents_with(self, other):
        """Moves the contents into another crate and takes what that one held in return.

        Name, description, responsible members, location, tags, the attention flag
        with its note, items and photos change places. Nothing is lost, and doing
        the same again undoes it. Raises ValueError if the two crates cannot be
        used for a move.
        """
        if other.pk == self.pk:
            raise ValueError('Quelle und Ziel sind dieselbe Crate.')
        if DEV_NULL_CODE in (self.code, other.code):
            raise ValueError(f'{DEV_NULL_CODE} ist /dev/null und nimmt an keinem Umzug teil.')
        with transaction.atomic():
            held = {
                crate.pk: (
                    list(crate.items.values_list('pk', flat=True)), list(crate.photos.values_list('pk', flat=True)),
                    list(crate.responsible.all()), list(crate.tags.all()),
                )
                for crate in (self, other)
            }
            for field in self.CONTENT_FIELDS:
                mine, theirs = getattr(self, field), getattr(other, field)
                setattr(self, field, theirs)
                setattr(other, field, mine)
            for crate, source in ((self, other), (other, self)):
                items, photos, responsible, tags = held[source.pk]
                crate.save()
                # The photo files stay in the folder of the crate they were taken for:
                # older states in the history refer to them by that path.
                Item.objects.filter(pk__in=items).update(crate=crate)
                Photo.objects.filter(pk__in=photos).update(crate=crate)
                crate.responsible.set(responsible)
                crate.tags.set(tags)


class Item(models.Model):
    crate = models.ForeignKey(Crate, verbose_name='Cargo Crate', on_delete=models.CASCADE, related_name='items')
    name = models.CharField('Bezeichnung', max_length=200)
    quantity = models.PositiveIntegerField('Menge', default=1)
    note = models.CharField('Notiz', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Inhaltsposition'
        verbose_name_plural = 'Inhalt'
        ordering = ['name']

    def __str__(self):
        return f'{self.quantity} × {self.name}'


def _photo_path(instance, filename):
    # The file name is random; the name from the phone is not kept.
    return f'crates/{instance.crate.code}/{filename}'


class Photo(models.Model):
    """A photo of the contents. The files live under MEDIA_ROOT and are only served to logged-in members."""

    crate = models.ForeignKey(Crate, verbose_name='Cargo Crate', on_delete=models.CASCADE, related_name='photos')
    image = models.FileField('Bild', upload_to=_photo_path)
    thumbnail = models.FileField('Vorschau', upload_to=_photo_path)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='Hochgeladen von', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField('Hochgeladen', auto_now_add=True)

    class Meta:
        verbose_name = 'Foto'
        verbose_name_plural = 'Fotos'
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'Foto {self.pk} von {self.crate.code}'

    @classmethod
    def create_from_upload(cls, crate, upload, member=None):
        """Scales down the upload and stores image and thumbnail. Raises PhotoError for unusable files."""
        from .photos import process_upload

        image, thumbnail = process_upload(upload)
        name = uuid.uuid4().hex
        photo = cls(crate=crate, uploaded_by=member)
        photo.image.save(f'{name}.jpg', ContentFile(image), save=False)
        photo.thumbnail.save(f'{name}-klein.jpg', ContentFile(thumbnail), save=False)
        photo.save()
        return photo


# Deleting a photo only removes its entry. The files stay as long as an older
# state in the history still shows them; "purge_photo_files" clears the rest.

# The history records a crate together with its items and photos (see history.py).
reversion.register(Crate, follow=('items', 'photos'))
reversion.register(Item)
reversion.register(Photo)
