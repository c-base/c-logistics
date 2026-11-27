import csv
import re

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.conf import settings
from django.db.models import Count, Q
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import generic

from .forms import CrateForm, ItemForm
from .labels import FONTS, label_png, labels_pdf, labels_ql_raster, public_url
from members.models import Member

from .models import DEV_NULL_CODE, Crate, Item, Photo, Tag, normalize_code
from .photos import PhotoError
from .reminders import make_plan, send_reminders


def manifest(request):
    """Web app manifest: lets c-logistics be installed on the phone as an app.

    Available without login because the browser loads it without a session.
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
        # Everything under the address belongs to the app – including /<ID> from QR code and NFC tag.
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
    """Finds the crate by the ID in the URL, case-insensitively."""

    model = Crate

    def get_object(self, queryset=None):
        return get_object_or_404(self.get_queryset(), code=normalize_code(self.kwargs['code']))


def selected_tags(request):
    """The tags being filtered by (?tag=eva:40c3&tag=transport:1), without duplicates."""
    names = [name.strip().lower() for name in request.GET.getlist('tag') if name.strip()]
    return list(dict.fromkeys(names))


def filtered_crates(request):
    """The crates of the list with search and filters from the address, ordered by ID."""
    qs = (
        Crate.objects.select_related('location')
        .prefetch_related('responsible', 'tags')
        .annotate(item_count=Count('items', distinct=True))
        .order_by('code')
    )
    query = request.GET.get('q', '').strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(code=normalize_code(query))
            | Q(description__icontains=query)
            | Q(attention_note__icontains=query)
            | Q(items__name__icontains=query)
            | Q(tags__scope__icontains=query)
            | Q(tags__value__icontains=query)
        ).distinct()
    if request.GET.get('mine'):
        qs = qs.filter(responsible=request.user)
    if request.GET.get('attention'):
        qs = qs.filter(needs_attention=True)
    # the crate has to carry every one of the chosen tags
    for name in selected_tags(request):
        tag = Tag.find(name)
        qs = qs.filter(tags=tag) if tag else qs.none()
    return qs


class CrateListView(LoginRequiredMixin, generic.ListView):
    model = Crate
    paginate_by = 50

    def get_queryset(self):
        return filtered_crates(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '').strip()
        context['mine'] = bool(self.request.GET.get('mine'))
        context['attention'] = bool(self.request.GET.get('attention'))
        context['tags'] = Tag.objects.all()
        context['selected_tags'] = selected_tags(self.request)
        # for "previous" and "next": all filters except the page
        params = self.request.GET.copy()
        params.pop('page', None)
        context['filter_query'] = params.urlencode()
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
        # neighbours in ID order: for paging through, on the phone by swiping
        neighbours = Crate.objects.only('code', 'name')
        context['previous_crate'] = neighbours.filter(code__lt=self.object.code).order_by('-code').first()
        context['next_crate'] = neighbours.filter(code__gt=self.object.code).order_by('code').first()
        return context


MAX_COPIES = 10


def copies_from(request):
    """How often each label or card is printed: ?copies=1…10, otherwise PRINT_COPIES."""
    try:
        copies = int(request.GET.get('copies', ''))
    except ValueError:
        copies = settings.PRINT_COPIES
    return min(max(copies, 1), MAX_COPIES)


class CardSheetMixin:
    """Print cards with all details and photos for the colour laser printer.

    A5 landscape: two cards on one A4 sheet in portrait.
    A6 landscape: four cards on one A4 sheet in landscape.
    """

    template_name = 'crates/crate_card.html'
    formats = {'a5': ('DIN A5', 2), 'a6': ('DIN A6', 4)}
    max_photos = 4

    def card_context(self, crates):
        chosen = self.request.GET.get('format')
        chosen = chosen if chosen in self.formats else 'a5'
        per_sheet = self.formats[chosen][1]
        copies = copies_from(self.request)
        # Copies of a crate follow one another, so with A5 they are on the same sheet.
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
            # selection without the number of copies, for the copies switches
            'selection_base': base.urlencode(),
            'format': chosen,
            'formats': [(key, label) for key, (label, _) in self.formats.items()],
            'per_sheet': per_sheet,
            'sheets': [cards[start:start + per_sheet] for start in range(0, len(cards), per_sheet)],
            'cards': cards,
            # selection including the number of copies but without the format, for the format switches
            'selection': query.urlencode(),
        }


class CrateCardView(LoginRequiredMixin, CrateLookupMixin, CardSheetMixin, generic.DetailView):
    """The card of a single crate."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.card_context([self.object]))
        context['back_url'] = self.object.get_absolute_url()
        return context


class CardSheetView(LoginRequiredMixin, CardSheetMixin, generic.TemplateView):
    """Cards of several crates together on as few sheets as possible: /cards/?c=0001&c=0002"""

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
    """The label as PNG or PDF in print resolution; printing is done from any device."""

    def get_queryset(self):
        return Crate.objects.all()

    def get(self, request, *args, **kwargs):
        crate = self.get_object()
        url = public_url(crate, request)
        # ?font=… shows the label in another font for comparison.
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


def selected_crates(request, data=None):
    """The crates checked in the list (?c=0001&c=0002), ordered by ID."""
    data = request.GET if data is None else data
    codes = {normalize_code(code) for code in data.getlist('c') if len(code) <= 4}
    return list(Crate.objects.filter(code__in=codes).order_by('code'))


class BulkTagView(LoginRequiredMixin, generic.View):
    """Adds or removes tags on all crates checked in the list.

    POST /tag/ with c=0001&c=0002, tags=transport:1 and action=add|remove
    """

    def post(self, request, *args, **kwargs):
        target = request.POST.get('next', '')
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            target = reverse('crates:list')
        crates = selected_crates(request, request.POST)
        names = request.POST.get('tags', '').replace(',', ' ').split()
        if not crates or not names:
            messages.error(request, 'Bitte Crates auswählen und ein Tag wählen.')
            return redirect(target)
        # only tags from the fixed selection; managers create new ones under "Tags verwalten"
        tags = [Tag.find(name) for name in names]
        if None in tags:
            unknown = ', '.join(name for name, tag in zip(names, tags) if tag is None)
            messages.error(request, f'Dieses Tag gibt es nicht: {unknown}.')
            return redirect(target)
        shown = ', '.join(str(tag) for tag in tags)
        count = f'{len(crates)} Crate{"s" if len(crates) != 1 else ""}'
        if request.POST.get('action') == 'remove':
            for crate in crates:
                crate.tags.remove(*tags)
            messages.success(request, f'{shown} von {count} entfernt.')
        else:
            for crate in crates:
                crate.tags.add(*tags)
            messages.success(request, f'{shown} an {count} gesetzt.')
        return redirect(target)


def _csv_cell(value):
    """As text for a spreadsheet: anything that starts like a formula is defused."""
    text = str(value)
    return f"'{text}" if text[:1] in ('=', '+', '-', '@') else text


class PackListView(LoginRequiredMixin, generic.View):
    """Packing list for ticking off: printable or as CSV.

    /packlist/?tag=eva:40c3            all crates matching the filters of the list
    /packlist/?c=0001&c=0002           the crates checked in the list
    format=csv                         a CSV file instead of the page
    format=md                          a Markdown file with a checklist instead of the page
    """

    def get(self, request, *args, **kwargs):
        tags = selected_tags(request)
        if request.GET.getlist('c'):
            crates = Crate.objects.filter(pk__in=[crate.pk for crate in selected_crates(request)])
            crates = crates.select_related('location').prefetch_related('responsible', 'tags')
            crates = list(crates.annotate(item_count=Count('items', distinct=True)).order_by('code'))
            tags = []
        else:
            crates = list(filtered_crates(request))
        title = f'Packliste {" ".join(tags)}' if tags else 'Packliste'
        if request.GET.get('format') == 'csv':
            return self.csv(request, crates, tags)
        if request.GET.get('format') == 'md':
            return self.markdown(request, crates, tags, title)
        params, markdown_params = request.GET.copy(), request.GET.copy()
        params['format'] = 'csv'
        markdown_params['format'] = 'md'
        # back to the list with the same filters; checked crates are not part of the address there
        back = request.GET.copy()
        for key in ('c', 'format', 'copies'):
            back.pop(key, None)
        context = {
            'crates': crates, 'title': title,
            'csv_url': f'?{params.urlencode()}',
            'markdown_url': f'?{markdown_params.urlencode()}',
            'back_url': f"{reverse('crates:list')}{'?' + back.urlencode() if back else ''}",
        }
        return render(request, 'crates/packlist.html', context)

    @staticmethod
    def filename(tags, extension):
        name = re.sub(r'[^A-Za-z0-9._-]+', '-', '-'.join(tags)).strip('-') or 'liste'
        return f'crates-{name}.{extension}'

    def markdown(self, request, crates, tags, title):
        """The packing list as a Markdown checklist for ticking off, e.g. for wiki, pad or issue.

        A list rather than a table: Markdown only has checkboxes (`- [ ]`) on list items.
        """

        def text(value):
            # single-line, and characters with a meaning in Markdown stay what they are
            return re.sub(r'([\\`*_\[\]<>|])', r'\\\1', ' '.join(str(value).split()))

        lines = [
            f'# {text(title)}', '',
            f'{len(crates)} Crate{"s" if len(crates) != 1 else ""} · Stand {date_format(timezone.localdate(), "SHORT_DATE_FORMAT")}', '',
        ]
        for crate in crates:
            details = [crate.get_size_display() + (f', {crate.height_mm} mm hoch' if crate.height_mm else '')]
            details.append(text(', '.join(str(member) for member in crate.responsible.all())))
            if crate.location:
                details.append(text(crate.location))
            details += [f'`{tag}`' for tag in crate.tags.all()]
            lines.append(f'- [ ] **[{crate.code}]({public_url(crate, request)})** {text(crate.name)} – {" · ".join(details)}')
            if crate.needs_attention:
                note = f': {text(crate.attention_note)}' if crate.attention_note else ''
                lines.append(f'  - ⚠ Needs attention{note}')
        response = HttpResponse('\n'.join(lines) + '\n', content_type='text/markdown; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{self.filename(tags, "md")}"'
        return response

    def csv(self, request, crates, tags):
        # semicolon and BOM so that a German Excel opens the file correctly without asking
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{self.filename(tags, "csv")}"'
        response.write('\ufeff')
        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'ID', 'Bezeichnung', 'Grundmaß', 'Höhe (mm)', 'Farbe', 'Verantwortliche', 'Lagerort', 'Tags',
            'Needs attention', 'Bemerkung', 'Positionen', 'Adresse',
        ])
        for crate in crates:
            writer.writerow([_csv_cell(value) for value in (
                crate.code, crate.name, crate.get_size_display(), crate.height_mm or '', crate.color,
                ', '.join(str(member) for member in crate.responsible.all()), crate.location or '',
                ' '.join(str(tag) for tag in crate.tags.all()),
                'ja' if crate.needs_attention else '', crate.attention_note, crate.item_count,
                public_url(crate, request),
            )])
        return response


class PrintDispatchView(LoginRequiredMixin, generic.View):
    """Target of the print bar in the list: redirects depending on the chosen variant.

    /print/?what=labels-pdf&copies=2&c=0001&c=0002
    """

    # variant -> (label in the selection, view, format)
    variants = {
        'labels-pdf': ('Labels als PDF', 'crates:labels', 'pdf'),
        'labels-ql': ('Labels als QL-Druckdatei (mit Schnitt)', 'crates:labels', 'ql'),
        'cards-a5': ('Karten DIN A5 (2 pro Blatt)', 'crates:cards', 'a5'),
        'cards-a6': ('Karten DIN A6 (4 pro Blatt)', 'crates:cards', 'a6'),
        'packlist': ('Packliste zum Ausdrucken', 'crates:packlist', 'html'),
        'packlist-csv': ('Packliste als CSV', 'crates:packlist', 'csv'),
        'packlist-md': ('Packliste als Markdown', 'crates:packlist', 'md'),
    }

    def get(self, request, *args, **kwargs):
        _, view, variant_format = self.variants.get(request.GET.get('what'), self.variants['labels-pdf'])
        query = request.GET.copy()
        query.pop('what', None)
        query['format'] = variant_format
        return redirect(f'{reverse(view)}?{query.urlencode()}')


class LabelSheetView(LoginRequiredMixin, generic.View):
    """Labels of several crates in one print file for the QL-700: /labels/?c=0001&c=0002

    format=pdf  one page per label; the printer driver cuts after every page
    format=ql   Brother raster data with a cut command after every label, raw to the printer
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
    """Suggestions for the search field of the responsible members: /members/search/?q=ali"""

    limit = 10

    def get(self, request, *args, **kwargs):
        members = Member.objects.exclude(username=Member.UNKNOWN_USERNAME)
        terms = request.GET.get('q', '').split()
        # every word has to occur, whether in the username, first name or last name
        for term in terms:
            members = members.filter(
                Q(username__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term)
            )
        found = members.order_by('username')[:self.limit] if terms else []
        return JsonResponse({'results': [member_choice(member) for member in found]})


def member_choice(member):
    """A member as the search field of the responsible members expects it."""
    return {'id': member.pk, 'label': member.label, 'username': member.username}


class ManagerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Only for the "Manager" role; all other logged-in users get 403."""

    def test_func(self):
        return self.request.user.is_manager


class MemberAddView(ManagerRequiredMixin, generic.View):
    """Reserves a member who has never logged in: POST /members/add/ with username=…"""

    def post(self, request, *args, **kwargs):
        try:
            member = Member.reserve(request.POST.get('username', ''))
        except ValueError as error:
            return JsonResponse({'error': str(error)}, status=400)
        return JsonResponse(member_choice(member))


class TagManageView(ManagerRequiredMixin, generic.TemplateView):
    """Managers create, rename and delete tags: /tags/"""

    template_name = 'crates/tag_manage.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tags'] = Tag.objects.annotate(crate_count=Count('crates'))
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        try:
            if action == 'add':
                names = Tag.parse_many(request.POST.get('names', ''))
                if not names:
                    raise ValueError('Bitte ein Tag angeben.')
                created = [
                    f'{scope}:{value}' for scope, value in names
                    if Tag.objects.get_or_create(scope=scope, value=value)[1]
                ]
                if created:
                    messages.success(request, f'Angelegt: {", ".join(created)}.')
                else:
                    messages.info(request, 'Diese Tags gab es schon.')
            else:
                tag = get_object_or_404(Tag, pk=request.POST.get('tag'))
                old = str(tag)
                if action == 'delete':
                    tag.delete()
                    messages.success(request, f'{old} gelöscht.')
                elif action == 'rename':
                    scope, value = Tag.parse(request.POST.get('name', ''))
                    if Tag.objects.filter(scope=scope, value=value).exclude(pk=tag.pk).exists():
                        raise ValueError(f'{scope}:{value} gibt es schon.')
                    tag.scope, tag.value = scope, value
                    tag.save()
                    if str(tag) != old:
                        messages.success(request, f'{old} heißt jetzt {tag}.')
        except ValueError as error:
            messages.error(request, str(error))
            if action == 'add':
                # the input stays so that it can be corrected
                return self.render_to_response(self.get_context_data(entered=request.POST.get('names', '')))
        return redirect('crates:tags')


class RemindView(ManagerRequiredMixin, generic.TemplateView):
    """Preview and sending of the reminders to the responsible members: /remind/"""

    template_name = 'crates/remind.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plan'] = make_plan()
        context['mail_enabled'] = settings.MAIL_ENABLED
        context['interval_days'] = settings.REMINDER_INTERVAL_DAYS
        return context

    def post(self, request, *args, **kwargs):
        target = f"{reverse('crates:list')}?attention=1"
        if not settings.MAIL_ENABLED:
            messages.error(request, 'Der Mailversand ist nicht eingerichtet (EMAIL_HOST fehlt).')
            return redirect('crates:remind')
        # The plan is rebuilt on submit: whoever has been reminded in the meantime gets no second mail.
        sent, failed = send_reminders(make_plan(), request.user, request)
        if sent:
            crates = len({crate.pk for reminder in sent for crate in reminder.crates})
            messages.success(request, f'{len(sent)} Mail{"s" if len(sent) != 1 else ""} verschickt, zu {crates} Crate{"s" if crates != 1 else ""}.')
        if failed:
            names = ', '.join(str(reminder.member) for reminder in failed)
            messages.error(request, f'Nicht verschickt werden konnte die Mail an: {names}.')
        if not sent and not failed:
            messages.info(request, 'Es gab niemanden zu erinnern.')
        return redirect(target)


class CrateFormMixin:
    form_class = CrateForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'user': self.request.user}


class CrateCreateView(ManagerRequiredMixin, CrateFormMixin, generic.CreateView):
    """For now only managers create new crates; every member may still edit."""

    model = Crate

    def get_initial(self):
        return {'responsible': [self.request.user.pk]}


class CrateUpdateView(LoginRequiredMixin, CrateLookupMixin, CrateFormMixin, generic.UpdateView):
    pass


class CrateDeleteView(LoginRequiredMixin, CrateLookupMixin, generic.DeleteView):
    success_url = reverse_lazy('crates:list')


class CrateMoveView(LoginRequiredMixin, CrateLookupMixin, generic.DetailView):
    """Moves the contents of a crate into another one: /<ID>/move/?to=<ID>

    GET shows both crates side by side – what moves, and what the target holds
    so far and loses. Only the POST from that preview moves anything.
    """

    template_name = 'crates/crate_move.html'

    def find_target(self, value):
        """The target crate for the entered ID and, if it cannot be used, the reason why."""
        value = value.strip()
        if not value:
            return None, ''
        if not re.fullmatch(r'[0-9A-Fa-f]{1,4}', value):
            return None, f'„{value}“ ist keine Crate-ID.'
        code = normalize_code(value)
        if code == self.object.code:
            return None, 'Das ist dieselbe Crate.'
        if code == DEV_NULL_CODE:
            return None, f'{DEV_NULL_CODE} ist /dev/null – dorthin zieht nichts um.'
        target = Crate.objects.filter(code=code).first()
        return target, '' if target else f'Die Crate {code} gibt es nicht.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entered = self.request.POST.get('to') or self.request.GET.get('to', '')
        context['entered'] = entered.strip()
        context['movable'] = self.object.code != DEV_NULL_CODE
        context['target'], context['target_error'] = self.find_target(entered)
        context['choices'] = Crate.objects.exclude(code__in=[self.object.code, DEV_NULL_CODE]).only('code', 'name')
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        target, _ = self.find_target(request.POST.get('to', ''))
        if target is None:
            return self.render_to_response(self.get_context_data())
        try:
            self.object.move_contents_to(target)
        except ValueError as error:
            messages.error(request, str(error))
            return self.render_to_response(self.get_context_data())
        messages.success(request, f'Der Inhalt von {self.object.code} ist nach {target.code} umgezogen. {self.object.code} ist jetzt leer.')
        return redirect(target)


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
    """Accepts one or more photos of the contents, straight from the phone camera or from the gallery."""

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
    """Finds the photo by crate ID and photo number; if the two do not match, the result is 404."""

    def get_photo(self):
        return get_object_or_404(Photo, pk=self.kwargs['pk'], crate__code=normalize_code(self.kwargs['code']))


class PhotoFileView(LoginRequiredMixin, PhotoLookupMixin, generic.View):
    """Serves image or thumbnail – like everything else only to logged-in members."""

    def get(self, request, *args, **kwargs):
        photo = self.get_photo()
        thumbnail = kwargs['variant'] == 'thumbnail'
        field = photo.thumbnail if thumbnail else photo.image
        try:
            response = FileResponse(field.open('rb'), content_type='image/jpeg')
        except FileNotFoundError:
            raise Http404('Die Bilddatei fehlt.')
        # Name when saving: crate ID and photo number, e.g. 10F0-7.jpg
        suffix = '-thumb' if thumbnail else ''
        response['Content-Disposition'] = f'inline; filename="{photo.crate.code}-{photo.pk}{suffix}.jpg"'
        # A photo never changes; at most it gets deleted.
        response['Cache-Control'] = 'private, max-age=86400'
        return response


class PhotoDeleteView(LoginRequiredMixin, PhotoLookupMixin, generic.DeleteView):
    model = Photo
    http_method_names = ['post']

    def get_object(self, queryset=None):
        return self.get_photo()

    def get_success_url(self):
        return f'{self.object.crate.get_absolute_url()}#fotos'
