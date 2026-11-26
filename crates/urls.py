from django.urls import path, register_converter
from django.views.generic import RedirectView

from . import views



class HexConverter:
    regex = '[0-9A-Fa-f]{1,4}'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(HexConverter, 'hex')

app_name = 'crates'

urlpatterns = [
    path('', views.CrateListView.as_view(), name='list'),
    path('manifest.webmanifest', views.manifest, name='manifest'),
    path('new/', views.CrateCreateView.as_view(), name='create'),
    path('cards/', views.CardSheetView.as_view(), name='cards'),
    path('labels/', views.LabelSheetView.as_view(), name='labels'),
    path('members/search/', views.MemberSearchView.as_view(), name='member-search'),
    path('members/add/', views.MemberAddView.as_view(), name='member-add'),
    path('remind/', views.RemindView.as_view(), name='remind'),
    path('tags/', views.TagManageView.as_view(), name='tags'),
    path('tag/', views.BulkTagView.as_view(), name='bulk-tag'),
    path('packlist/', views.PackListView.as_view(), name='packlist'),
    path('print/', views.PrintDispatchView.as_view(), name='print'),
    path('item/<int:pk>/', views.ItemUpdateView.as_view(), name='item-update'),
    path('item/<int:pk>/delete/', views.ItemDeleteView.as_view(), name='item-delete'),
    # Target of NFC tag and QR code: https://crates.c-base.org/<ID>
    # Careful: every path of at most four hex characters thereby belongs to a crate.
    # New pages must therefore not be called e.g. /add, /feed or /cafe.
    path('<hex:code>', views.CrateDetailView.as_view(), name='detail'),
    path('<hex:code>/label.png', views.CrateLabelView.as_view(), {'extension': 'png'}, name='label'),
    path('<hex:code>/label.pdf', views.CrateLabelView.as_view(), {'extension': 'pdf'}, name='label-pdf'),
    path('<hex:code>/card/', views.CrateCardView.as_view(), name='card'),
    path('<hex:code>/edit/', views.CrateUpdateView.as_view(), name='update'),
    path('<hex:code>/delete/', views.CrateDeleteView.as_view(), name='delete'),
    path('<hex:code>/items/', views.ItemCreateView.as_view(), name='item-create'),
    path('<hex:code>/pics/', views.PhotoUploadView.as_view(), name='photo-upload'),
    path('<hex:code>/pic/<int:pk>.jpg', views.PhotoFileView.as_view(), {'variant': 'image'}, name='photo'),
    path('<hex:code>/pic/<int:pk>-thumb.jpg', views.PhotoFileView.as_view(), {'variant': 'thumbnail'}, name='photo-thumbnail'),
    path('<hex:code>/pic/<int:pk>/delete/', views.PhotoDeleteView.as_view(), name='photo-delete'),
    # Earlier spellings redirect to the short address.
    path('<hex:code>/', RedirectView.as_view(pattern_name='crates:detail', permanent=True)),
    path('c/<hex:code>/', RedirectView.as_view(pattern_name='crates:detail', permanent=True)),
]
