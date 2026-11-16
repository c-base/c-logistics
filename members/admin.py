from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Member


@admin.register(Member)
class MemberAdmin(UserAdmin):
    readonly_fields = ['oidc_sub']
    fieldsets = UserAdmin.fieldsets + (('Single Sign-on', {'fields': ['oidc_sub']}),)
