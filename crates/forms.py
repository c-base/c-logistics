from django import forms

from django.db.models import Case, When

from members.models import Member

from .models import Crate, Item


class BootstrapFormMixin:
    """Gibt Formularen Bootstrap-5-Markup: Klassen an den Feldern, eigenes Feld-Template."""

    template_name = 'forms/bootstrap.html'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            css_class = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css_class}".strip()


class ResponsibleWidget(forms.CheckboxSelectMultiple):
    """Wenige Member als Haken, alle übrigen über ein Suchfeld darunter."""

    template_name = 'crates/widgets/responsible.html'


class CrateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Crate
        fields = ['name', 'description', 'size', 'height_mm', 'color', 'responsible', 'location', 'needs_attention']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'responsible': ResponsibleWidget,
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unknown = Member.unknown()
        field = self.fields['responsible']
        # „unbecannt“ steht oben und ist gewählt, solange niemand sonst eingetragen ist.
        own = user.pk if user is not None else None
        members = Member.objects.order_by(
            Case(When(pk=self.unknown.pk, then=0), When(pk=own, then=1), default=2), 'username',
        )
        field.queryset = members
        field.required = False
        field.help_text = 'Ohne Auswahl gilt „unbecannt“.'
        # für das Skript im Formular, das den Haken bei „unbecannt“ mitführt
        field.widget.attrs['data-unknown'] = self.unknown.pk
        # Gültig sind alle Member, als Haken stehen aber nur „unbecannt“, man selbst
        # und die schon gewählten da. Alle anderen kommen über die Suche dazu.
        shown = {self.unknown.pk, own, *self._selected_members()}
        field.widget.choices = [(member.pk, str(member)) for member in members.filter(pk__in=shown - {None})]

    def _selected_members(self):
        """Die IDs der gewählten Member: aus der Eingabe, sonst von der Crate, sonst vorbelegt."""
        if self.is_bound:
            name = self.add_prefix('responsible')
            values = self.fields['responsible'].widget.value_from_datadict(self.data, self.files, name) or []
            return {int(value) for value in values if str(value).isdecimal()}
        if self.instance.pk:
            return set(self.instance.responsible.values_list('pk', flat=True))
        return {getattr(member, 'pk', member) for member in self.initial.get('responsible', [])}

    def clean_responsible(self):
        """„unbecannt“ gilt genau dann, wenn kein Member verantwortlich ist."""
        known = [member for member in self.cleaned_data['responsible'] if member.pk != self.unknown.pk]
        return known or [self.unknown]


class ItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'quantity', 'note']
