from django.contrib import admin
from django.db.models import Count
from reversion.admin import VersionAdmin

from .models import Crate, Item, Location, Photo, Tag


class ItemInline(admin.TabularInline):
    model = Item
    extra = 1


@admin.register(Crate)
class CrateAdmin(VersionAdmin):
    list_display = ['name', 'code', 'size', 'location', 'needs_attention', 'updated_at']
    list_filter = ['needs_attention', 'tags', 'size', 'location', 'responsible']
    search_fields = ['name', 'code', 'description', 'items__name']
    readonly_fields = ['code', 'attention_reminded_at']
    filter_horizontal = ['responsible', 'tags']
    inlines = [ItemInline]


admin.site.register(Location)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'scope', 'value', 'crate_count']
    list_filter = ['scope']
    search_fields = ['scope', 'value']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(crate_count=Count('crates'))

    @admin.display(description='Crates', ordering='crate_count')
    def crate_count(self, tag):
        return tag.crate_count


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'crate', 'uploaded_by', 'created_at']
    readonly_fields = ['image', 'thumbnail', 'uploaded_by']
