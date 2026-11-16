from django.contrib import admin

from .models import Crate, Item, Location


class ItemInline(admin.TabularInline):
    model = Item
    extra = 1


@admin.register(Crate)
class CrateAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'size', 'location', 'updated_at']
    list_filter = ['size', 'location', 'responsible']
    search_fields = ['name', 'code', 'description', 'items__name']
    readonly_fields = ['code']
    filter_horizontal = ['responsible']
    inlines = [ItemInline]


admin.site.register(Location)
