from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.db.models import Count, Q
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.views import generic

from .forms import CrateForm, ItemForm
from .labels import FONTS, label_png, labels_pdf, labels_ql_raster, public_url
from members.models import Member

from .models import Crate, Item, Photo, normalize_code
from .photos import PhotoError


def manifest(request):
    """Web-App-Manifest: damit lässt sich c-logistics auf dem Telefon als App installieren.

    Ohne Anmeldung abrufbar, weil der Browser es ohne Sitzung lädt.
    """
    def icon(name, size, purpose='any'):
        return {'src': static(f'crates/icons/{name}'), 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': purpose}

    data = {
        'id': '/',
        'name': 'c-base cargo crates',
        'short_name': 'crates',
        'description': 'Verwaltung der c-base cargo crates',
        'lang': 'de',
        'start_url': '/',
        # Alles unter der Adresse gehört zur App – auch /<ID> aus QR-Code und NFC-Tag.
        'scope': '/',
        'display': 'standalone',
        'background_color': '#060606',
        'theme_color': '#060606',
        'icons': [
            icon('icon-192.png', 192),
            icon('icon-512.png', 512),
            icon('maskable-512.png', 512, 'maskable'),
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json')


class CrateLookupMixin:
    """Findet die Crate über die ID in der URL, unabhängig von Groß-/Kleinschreibung."""

    model = Crate

    def get_object(self, queryset=None):
        return get_object_or_404(self.get_queryset(), code=normalize_code(self.kwargs['code']))


class CrateListView(LoginRequiredMixin, generic.ListView):
    model = Crate
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Crate.objects.select_related('location')
            .prefetch_related('responsible')
            .annotate(item_count=Count('items', distinct=True))
            .order_by('code')
        )
        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(code=normalize_code(query))
                | Q(description__icontains=query)
                | Q(attention_note__icontains=query)
                | Q(items__name__icontains=query)
            ).distinct()
        if self.request.GET.get('mine'):
            qs = qs.filter(responsible=self.request.user)
        if self.request.GET.get('attention'):
            qs = qs.filter(needs_attention=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '').strip()
        context['mine'] = bool(self.request.GET.get('mine'))
        context['attention'] = bool(self.request.GET.get('attention'))
        context['copies'] = settings.PRINT_COPIES
        context['max_copies'] = MAX_COPIES
        context['print_variants'] = [(key, label) for key, (label, _, _) in PrintDispatchView.variants.items()]
        return context


class CrateDetailView(LoginRequiredMixin, CrateLookupMixin, generic.DetailView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_form'] = ItemForm()
        context['public_url'] = public_url(self.object, self.request)
        context['base_url_configured'] = bool(settings.PUBLIC_BASE_URL)
        context['copies'] = settings.PRINT_COPIES
        return context


MAX_COPIES = 10


def copies_from(request):
    """Wie oft jedes Label bzw. jede Karte gedruckt wird: ?copies=1…10, sonst PRINT_COPIES."""
    try:
        copies = int(request.GET.get('copies', ''))
    except ValueError:
        copies = settings.PRINT_COPIES
    return min(max(copies, 1), MAX_COPIES)


class CardSheetMixin:
    """Druckkarten mit allen Angaben und Fotos für den Farblaser.

    A5 quer: zwei Karten auf einem A4-Blatt im Hochformat.
    A6 quer: vier Karten auf einem A4-Blatt im Querformat.
    """

    template_name = 'crates/crate_card.html'
    formats = {'a5': ('DIN A5', 2), 'a6': ('DIN A6', 4)}
    max_photos = 4

    def card_context(self, crates):
        chosen = self.request.GET.get('format')
        chosen = chosen if chosen in self.formats else 'a5'
        per_sheet = self.formats[chosen][1]
        copies = copies_from(self.request)
        # Exemplare einer Crate stehen hintereinander, bei A5 also auf demselben Blatt.
        cards = [
            {
                'crate': crate,
                'photos': list(crate.photos.all()[:self.max_photos]),
                'public_url': public_url(crate, self.request),
            }
            for crate in crates
            for _ in range(copies)
        ]
        query = self.request.GET.copy()
        query.pop('format', None)
        query['copies'] = copies
        base = query.copy()
        base.pop('copies', None)
        return {
            'crate_count': len(crates),
            'copies': copies,
            'copy_choices': sorted({1, 2, 3, 4, copies}),
            # Auswahl ohne Kopienzahl, für die Umschalter der Exemplare
            'selection_base': base.urlencode(),
            'format': chosen,
            'formats': [(key, label) for key, (label, _) in self.formats.items()],
            'per_sheet': per_sheet,
            'sheets': [cards[start:start + per_sheet] for start in range(0, len(cards), per_sheet)],
            'cards': cards,
            # Auswahl samt Kopienzahl, aber ohne Format, für die Umschalter des Formats
            'selection': query.urlencode(),
        }


class CrateCardView(LoginRequiredMixin, CrateLookupMixin, CardSheetMixin, generic.DetailView):
    """Die Karte einer einzelnen Crate."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.card_context([self.object]))
        context['back_url'] = self.object.get_absolute_url()
        return context


class CardSheetView(LoginRequiredMixin, CardSheetMixin, generic.TemplateView):
    """Karten mehrerer Crates zusammen auf möglichst wenigen Blättern: /cards/?c=0001&c=0002"""

    def get(self, request, *args, **kwargs):
        self.crates = selected_crates(request)
        if not self.crates:
            messages.error(request, 'Bitte mindestens eine Crate auswählen.')
            return redirect('crates:list')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.card_context(self.crates))
        context['back_url'] = reverse('crates:list')
        return context


class CrateLabelView(LoginRequiredMixin, CrateLookupMixin, generic.View):
    """Das Label als PNG oder PDF in Druckauflösung; gedruckt wird von einem beliebigen Gerät."""

    def get_queryset(self):
        return Crate.objects.all()

    def get(self, request, *args, **kwargs):
        crate = self.get_object()
        url = public_url(crate, request)
        # ?font=… zeigt das Label zum Vergleich in einer anderen Schrift.
        font = request.GET.get('font')
        if font not in FONTS:
            font = None
        if kwargs['extension'] == 'pdf':
            pages = [(url, crate.code)] * copies_from(request)
            response = HttpResponse(labels_pdf(pages, font=font), content_type='application/pdf')
        else:
            response = HttpResponse(label_png(url, crate.code, font=font), content_type='image/png')
        disposition = 'attachment' if request.GET.get('download') else 'inline'
        response['Content-Disposition'] = f'{disposition}; filename="crate-{crate.code}.{kwargs["extension"]}"'
        return response


def selected_crates(request):
    """Die in der Liste angehakten Crates (?c=0001&c=0002), nach ID sortiert."""
    codes = {normalize_code(code) for code in request.GET.getlist('c') if len(code) <= 4}
    return list(Crate.objects.filter(code__in=codes).order_by('code'))


class PrintDispatchView(LoginRequiredMixin, generic.View):
    """Ziel der Druckleiste in der Liste: leitet je nach gewählter Variante weiter.

    /print/?what=labels-pdf&copies=2&c=0001&c=0002
    """

    # Variante -> (Bezeichnung in der Auswahl, Ansicht, Format)
    variants = {
        'labels-pdf': ('Labels als PDF', 'crates:labels', 'pdf'),
        'labels-ql': ('Labels als QL-Druckdatei (mit Schnitt)', 'crates:labels', 'ql'),
        'cards-a5': ('Karten DIN A5 (2 pro Blatt)', 'crates:cards', 'a5'),
        'cards-a6': ('Karten DIN A6 (4 pro Blatt)', 'crates:cards', 'a6'),
    }

    def get(self, request, *args, **kwargs):
        _, view, variant_format = self.variants.get(request.GET.get('what'), self.variants['labels-pdf'])
        query = request.GET.copy()
        query.pop('what', None)
        query['format'] = variant_format
        return redirect(f'{reverse(view)}?{query.urlencode()}')


class LabelSheetView(LoginRequiredMixin, generic.View):
    """Labels mehrerer Crates in einer Druckdatei für den QL-700: /labels/?c=0001&c=0002

    format=pdf  eine Seite pro Label; der Druckertreiber schneidet nach jeder Seite
    format=ql   Brother-Rasterdaten mit Schneidbefehl nach jedem Label, roh an den Drucker
    """

    def get(self, request, *args, **kwargs):
        crates = selected_crates(request)
        if not crates:
            messages.error(request, 'Bitte mindestens eine Crate auswählen.')
            return redirect('crates:list')
        copies = copies_from(request)
        labels = [(public_url(crate, request), crate.code) for crate in crates for _ in range(copies)]
        name = f'crate-{crates[0].code}' if len(crates) == 1 else f'crates-{crates[0].code}-{crates[-1].code}'
        if request.GET.get('format') == 'ql':
            try:
                data = labels_ql_raster(labels)
            except ValueError as error:
                messages.error(request, str(error))
                return redirect('crates:list')
            response = HttpResponse(data, content_type='application/octet-stream')
            response['Content-Disposition'] = f'attachment; filename="{name}-ql700.bin"'
        else:
            response = HttpResponse(labels_pdf(labels), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{name}-labels.pdf"'
        return response


class MemberSearchView(LoginRequiredMixin, generic.View):
    """Vorschläge für das Suchfeld bei den Verantwortlichen: /members/search/?q=ali"""

    limit = 10

    def get(self, request, *args, **kwargs):
        members = Member.objects.exclude(username=Member.UNKNOWN_USERNAME)
        terms = request.GET.get('q', '').split()
        # jedes Wort muss vorkommen, egal ob im Nutzernamen, Vor- oder Nachnamen
        for term in terms:
            members = members.filter(
                Q(username__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term)
            )
        found = members.order_by('username')[:self.limit] if terms else []
        results = [{'id': member.pk, 'label': str(member), 'username': member.username} for member in found]
        return JsonResponse({'results': results})


class CrateFormMixin:
    form_class = CrateForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'user': self.request.user}


class CrateCreateView(LoginRequiredMixin, CrateFormMixin, generic.CreateView):
    model = Crate

    def get_initial(self):
        return {'responsible': [self.request.user.pk]}


class CrateUpdateView(LoginRequiredMixin, CrateLookupMixin, CrateFormMixin, generic.UpdateView):
    pass


class CrateDeleteView(LoginRequiredMixin, CrateLookupMixin, generic.DeleteView):
    success_url = reverse_lazy('crates:list')


class ItemCreateView(LoginRequiredMixin, generic.CreateView):
    model = Item
    form_class = ItemForm

    def dispatch(self, request, *args, **kwargs):
        self.crate = get_object_or_404(Crate, code=normalize_code(kwargs['code']))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return redirect(self.crate)

    def form_valid(self, form):
        form.instance.crate = self.crate
        form.save()
        return redirect(self.crate)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['crate'] = self.crate
        return context


class ItemUpdateView(LoginRequiredMixin, generic.UpdateView):
    model = Item
    form_class = ItemForm

    def get_success_url(self):
        return self.object.crate.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['crate'] = self.object.crate
        return context


class ItemDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = Item
    http_method_names = ['post']

    def get_success_url(self):
        return self.object.crate.get_absolute_url()


class PhotoUploadView(LoginRequiredMixin, generic.View):
    """Nimmt ein oder mehrere Fotos vom Inhalt entgegen, direkt aus der Handykamera oder aus der Galerie."""

    def post(self, request, *args, **kwargs):
        crate = get_object_or_404(Crate, code=normalize_code(kwargs['code']))
        uploads = request.FILES.getlist('images')
        if not uploads:
            messages.error(request, 'Es wurde kein Bild ausgewählt.')
        for upload in uploads:
            try:
                Photo.create_from_upload(crate, upload, request.user)
            except PhotoError as error:
                messages.error(request, str(error))
        return redirect(f'{crate.get_absolute_url()}#fotos')


class PhotoLookupMixin:
    """Findet das Foto über Crate-ID und Fotonummer; passen beide nicht zusammen, gibt es 404."""

    def get_photo(self):
        return get_object_or_404(Photo, pk=self.kwargs['pk'], crate__code=normalize_code(self.kwargs['code']))


class PhotoFileView(LoginRequiredMixin, PhotoLookupMixin, generic.View):
    """Liefert Bild oder Vorschau aus – wie alles andere nur für angemeldete Member."""

    def get(self, request, *args, **kwargs):
        photo = self.get_photo()
        thumbnail = kwargs['variant'] == 'thumbnail'
        field = photo.thumbnail if thumbnail else photo.image
        try:
            response = FileResponse(field.open('rb'), content_type='image/jpeg')
        except FileNotFoundError:
            raise Http404('Die Bilddatei fehlt.')
        # Name beim Speichern: Crate-ID und Fotonummer, z. B. 10F0-7.jpg
        suffix = '-thumb' if thumbnail else ''
        response['Content-Disposition'] = f'inline; filename="{photo.crate.code}-{photo.pk}{suffix}.jpg"'
        # Ein Foto ändert sich nie, es wird höchstens gelöscht.
        response['Cache-Control'] = 'private, max-age=86400'
        return response


class PhotoDeleteView(LoginRequiredMixin, PhotoLookupMixin, generic.DeleteView):
    model = Photo
    http_method_names = ['post']

    def get_object(self, queryset=None):
        return self.get_photo()

    def get_success_url(self):
        return f'{self.object.crate.get_absolute_url()}#fotos'
