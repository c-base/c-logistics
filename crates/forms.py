from django import forms

from .models import Crate, Item


class CrateForm(forms.ModelForm):
    class Meta:
        model = Crate
        fields = ['name', 'description', 'size', 'height_mm', 'color', 'responsible', 'location']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'responsible': forms.CheckboxSelectMultiple,
        }


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'quantity', 'note']
