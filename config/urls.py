from django.contrib import admin
from django.urls import include, path

from members import views as member_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', member_views.MemberLoginView.as_view(), name='login'),
    path('accounts/oidc/login/', member_views.oidc_login, name='oidc-login'),
    path('accounts/oidc/callback/', member_views.oidc_callback, name='oidc-callback'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('crates.urls')),
]
