from django.urls import path, register_converter

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
    path('neu/', views.CrateCreateView.as_view(), name='create'),
    # Ziel von NFC-Tag und QR-Code: die Crate-ID ist der letzte Teil der URL.
    path('c/<hex:code>/', views.CrateDetailView.as_view(), name='detail'),
    path('c/<hex:code>/label.png', views.CrateLabelView.as_view(), {'extension': 'png'}, name='label'),
    path('c/<hex:code>/label.pdf', views.CrateLabelView.as_view(), {'extension': 'pdf'}, name='label-pdf'),
    path('c/<hex:code>/bearbeiten/', views.CrateUpdateView.as_view(), name='update'),
    path('c/<hex:code>/loeschen/', views.CrateDeleteView.as_view(), name='delete'),
    path('c/<hex:code>/inhalt/', views.ItemCreateView.as_view(), name='item-create'),
    path('inhalt/<int:pk>/', views.ItemUpdateView.as_view(), name='item-update'),
    path('inhalt/<int:pk>/loeschen/', views.ItemDeleteView.as_view(), name='item-delete'),
]
