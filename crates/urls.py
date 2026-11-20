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
    path('new/', views.CrateCreateView.as_view(), name='create'),
    path('cards/', views.CardSheetView.as_view(), name='cards'),
    path('labels/', views.LabelSheetView.as_view(), name='labels'),
    path('item/<int:pk>/', views.ItemUpdateView.as_view(), name='item-update'),
    path('item/<int:pk>/delete/', views.ItemDeleteView.as_view(), name='item-delete'),
    # Ziel von NFC-Tag und QR-Code: https://crates.c-base.org/<ID>
    # Achtung: Jeder Pfad aus höchstens vier Hex-Zeichen gehört damit einer Crate.
    # Neue Seiten dürfen deshalb nicht z. B. /add, /feed oder /cafe heißen.
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
    # Frühere Schreibweisen leiten auf die kurze Adresse um.
    path('<hex:code>/', RedirectView.as_view(pattern_name='crates:detail', permanent=True)),
    path('c/<hex:code>/', RedirectView.as_view(pattern_name='crates:detail', permanent=True)),
]
