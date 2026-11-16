from django import forms

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


class ItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'quantity', 'note']
