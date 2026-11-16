from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.urls import reverse

CODE_DIGITS = 4
MAX_NUMBER = 16 ** CODE_DIGITS - 1


def format_code(number):
    """Laufende Nummer als vierstellige Hex-ID, z. B. 26 -> '001A'."""
    return f'{number:0{CODE_DIGITS}X}'


def normalize_code(value):
    """Macht aus Eingaben wie '1a' oder '001a' die gespeicherte ID '001A'."""
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
        if self.code:
            return super().save(*args, **kwargs)
        # Zwei gleichzeitig angelegte Crates könnten dieselbe Nummer ziehen; dann neu versuchen.
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
