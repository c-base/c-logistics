from django import forms

from django.db.models import Case, When

from members.models import Member

from .models import Crate, Item, Tag


class BootstrapFormMixin:
    """Gives forms Bootstrap 5 markup: classes on the fields, a custom field template."""

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
    """A few members as checkboxes, all others via a search field below."""

    template_name = 'crates/widgets/responsible.html'
    # Managers may reserve members who have never logged in.
    can_add = False

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['can_add'] = self.can_add
        return context


class CrateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Crate
        fields = ['name', 'description', 'size', 'height_mm', 'color', 'responsible', 'location', 'tags', 'needs_attention', 'attention_note']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'attention_note': forms.Textarea(attrs={'rows': 2}),
            'responsible': ResponsibleWidget,
            'tags': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unknown = Member.unknown()
        field = self.fields['responsible']
        # "unbecannt" comes first and is selected as long as nobody else is entered.
        own = user.pk if user is not None else None
        members = Member.objects.order_by(
            Case(When(pk=self.unknown.pk, then=0), When(pk=own, then=1), default=2), 'username',
        )
        field.queryset = members
        field.required = False
        field.help_text = 'Ohne Auswahl gilt „unbecannt“.'
        # for the script in the form that keeps the "unbecannt" checkbox in sync
        field.widget.attrs['data-unknown'] = self.unknown.pk
        # All members are valid, but only "unbecannt", oneself and the ones already
        # chosen are shown as checkboxes. All others are added via the search.
        shown = {self.unknown.pk, own, *self._selected_members()}
        field.widget.choices = [(member.pk, member.label) for member in members.filter(pk__in=shown - {None})]
        field.widget.can_add = bool(user is not None and user.is_manager)

        tags = self.fields['tags']
        tags.help_text = (
            'Neue Tags legst du unter „Tags verwalten“ an.' if user is not None and user.is_manager
            else 'Fehlt ein Tag? Manager können neue anlegen.'
        )

    def _selected_members(self):
        """The IDs of the chosen members: from the input, else from the crate, else the initial value."""
        if self.is_bound:
            name = self.add_prefix('responsible')
            values = self.fields['responsible'].widget.value_from_datadict(self.data, self.files, name) or []
            return {int(value) for value in values if str(value).isdecimal()}
        if self.instance.pk:
            return set(self.instance.responsible.values_list('pk', flat=True))
        return {getattr(member, 'pk', member) for member in self.initial.get('responsible', [])}

    def clean_responsible(self):
        """"unbecannt" applies exactly when no member is responsible."""
        known = [member for member in self.cleaned_data['responsible'] if member.pk != self.unknown.pk]
        return known or [self.unknown]


class ItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'quantity', 'note']
