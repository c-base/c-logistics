from django.contrib.auth.forms import AuthenticationForm

from crates.forms import BootstrapFormMixin


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass
