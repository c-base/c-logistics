from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import generic

from .forms import CrateForm, ItemForm
from .labels import FONTS, label_pdf, label_png, public_url
from .models import Crate, Item, normalize_code


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
                | Q(items__name__icontains=query)
            ).distinct()
        if self.request.GET.get('mine'):
            qs = qs.filter(responsible=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '').strip()
        context['mine'] = bool(self.request.GET.get('mine'))
        return context


class CrateDetailView(LoginRequiredMixin, CrateLookupMixin, generic.DetailView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_form'] = ItemForm()
        context['public_url'] = public_url(self.object, self.request)
        context['base_url_configured'] = bool(settings.PUBLIC_BASE_URL)
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
            response = HttpResponse(label_pdf(url, crate.code, font=font), content_type='application/pdf')
        else:
            response = HttpResponse(label_png(url, crate.code, font=font), content_type='image/png')
        disposition = 'attachment' if request.GET.get('download') else 'inline'
        response['Content-Disposition'] = f'{disposition}; filename="crate-{crate.code}.{kwargs["extension"]}"'
        return response


class CrateCreateView(LoginRequiredMixin, generic.CreateView):
    model = Crate
    form_class = CrateForm

    def get_initial(self):
        return {'responsible': [self.request.user.pk]}


class CrateUpdateView(LoginRequiredMixin, CrateLookupMixin, generic.UpdateView):
    form_class = CrateForm


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
