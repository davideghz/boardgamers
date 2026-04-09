from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView, RedirectURLMixin
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView
from django.contrib.auth.views import (
    PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView
)
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.utils.translation import gettext_lazy as _
from django.views import generic, View

from meta.views import Meta

from webapp import emails
from webapp.forms import UserRegistrationForm, CustomPasswordResetForm, CustomSetPasswordForm
from webapp.messages import MSG_EMAIL_VERIFICATION_CODE_SENT


# SIGNUP

class SignupView(generic.CreateView, RedirectURLMixin):
    form_class = UserRegistrationForm
    template_name = 'auth/signup.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('account-index')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta'] = Meta(
            title=_("Register - Board-Gamers.com"),
            description=_("Join the community to find game tables nd meet other players."),
        )
        return context

    def form_valid(self, form):
        user = form.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("login")


# LOGIN AND LOGOUT

class CustomLoginView(LoginView):
    template_name = 'auth/login.html'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta'] = Meta(
            title=_("Login - Board-Gamers.com"),
            description=_("Access your account to manage your game tables and profile."),
        )
        return context

    def get_success_url(self):
        next_url = self.request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return next_url
        return reverse("home")


class CustomLogoutView(LogoutView):
    def get_success_url(self):
        return reverse("home")


# PASSWORD CHANGE

class CustomPasswordChangeView(PasswordChangeView):
    template_name = 'auth/password_change_form.html'

    def get_form_class(self):
        if not self.request.user.has_usable_password():
            return SetPasswordForm
        return super().get_form_class()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_set_password'] = not self.request.user.has_usable_password()
        return context


class CustomPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = 'auth/password_change_done.html'


# PASSWORD RESET

class CustomPasswordResetView(PasswordResetView):
    form_class = CustomPasswordResetForm
    template_name = 'auth/password_reset_form.html'


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'auth/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = CustomSetPasswordForm
    template_name = 'auth/password_reset_confirm.html'


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'auth/password_reset_complete.html'


# VERIFY EMAIL

class VerifyEmailView(View):
    def get(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64)
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if default_token_generator.check_token(user, token):
            user.user_profile.is_email_verified = True
            user.user_profile.save()
            messages.success(request, "Email verified. You can now Login")
            return redirect('login')
        else:
            messages.error(request, "Error. Invalid verification code.", extra_tags="danger")
            return redirect("home")


def send_email_verification_code(request):
    emails.send_user_email_verification_code(request.user.user_profile)
    messages.info(request, MSG_EMAIL_VERIFICATION_CODE_SENT)
    return redirect('home')

