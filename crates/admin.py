from django.contrib import admin

from .models import Crate, Item, Location, Photo


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


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'crate', 'uploaded_by', 'created_at']
    readonly_fields = ['image', 'thumbnail', 'uploaded_by']
