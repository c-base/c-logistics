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


class CrateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Crate
        fields = ['name', 'description', 'size', 'height_mm', 'color', 'responsible', 'location']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'responsible': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unknown = Member.unknown()
        field = self.fields['responsible']
        # „unbecannt“ steht oben und ist gewählt, solange niemand sonst eingetragen ist.
        field.queryset = Member.objects.order_by(
            Case(When(pk=self.unknown.pk, then=0), default=1), 'username',
        )
        field.required = False
        field.help_text = 'Ohne Auswahl gilt „unbecannt“.'
        # für das Skript im Formular, das den Haken bei „unbecannt“ mitführt
        field.widget.attrs['data-unknown'] = self.unknown.pk

    def clean_responsible(self):
        """„unbecannt“ gilt genau dann, wenn kein Member verantwortlich ist."""
        known = [member for member in self.cleaned_data['responsible'] if member.pk != self.unknown.pk]
        return known or [self.unknown]


class ItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'quantity', 'note']
