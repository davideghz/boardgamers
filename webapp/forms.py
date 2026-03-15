from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import ModelForm, CharField, TextInput, PasswordInput, Textarea, \
    Select, Form, EmailInput, NumberInput, DateInput, TimeInput, FileInput, HiddenInput, CheckboxInput, \
    ModelMultipleChoiceField, EmailField, ModelChoiceField, BooleanField, URLInput, ChoiceField
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox, ReCaptchaV2Invisible

from webapp.models import Table, UserProfile, Comment, Player, Location, GuestProfile, Member, Game, LocationGame

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from dal import autocomplete


class CustomTextInputWidget(TextInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={
            'class': 'form-control', 'placeholder': placeholder, 'autocomplete': 'new-password', **(attrs or {})})


class CustomPasswordInputWidget(PasswordInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={
            'class': 'form-control', 'placeholder': placeholder, 'autocomplete': 'new-password', **(attrs or {})})


class CustomSelectWidget(Select):
    def __init__(self, attrs=None, choices=()):
        super().__init__(attrs)
        self.attrs.setdefault('class', 'form-select')
        self.choices = choices


class CustomTextareaWidget(Textarea):
    def __init__(self, attrs=None, placeholder="", style="min-height: 100px"):
        super().__init__(attrs={
            'class': 'form-control',
            'placeholder': placeholder,
            'style': style,
            **(attrs or {})
        })


class CustomEmailWidget(EmailInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={'class': 'form-control', 'placeholder': placeholder, **(attrs or {})})


class CustomDateInputWidget(DateInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(
            attrs={
                'type': 'date',
                'class': 'form-control date-input',
                'placeholder': placeholder, **(attrs or {})
            },
            format='%Y-%m-%d'
        )


class CustomCheckboxInputWidget(CheckboxInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={
            'class': 'form-check-input',
            'role': 'switch',
            'autocomplete': 'new-password', **(attrs or {})})




_TW_INPUT = (
    'w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 '
    'placeholder:text-slate-400 focus:outline-none focus:ring-2 '
    'focus:ring-blue-500/20 focus:border-blue-500 bg-white transition-colors'
)
_TW_INPUT_ERR = (
    'w-full rounded-xl border border-red-400 px-4 py-3 text-sm text-slate-700 '
    'placeholder:text-slate-400 focus:outline-none focus:ring-2 '
    'focus:ring-red-400/20 focus:border-red-400 bg-white transition-colors'
)


class TailwindForm(Form):
    def __init__(self, *args, **kwargs):
        super(Form, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            w = field.widget
            if isinstance(w, HiddenInput):
                continue
            if hasattr(w, 'url'):  # dal autocomplete — leave untouched
                continue
            has_err = bool(self.errors.get(field_name))
            css = _TW_INPUT_ERR if has_err else _TW_INPUT
            if isinstance(w, TimeInput):
                field.widget = TimeInput(format='%H:%M', attrs={'type': 'time', 'class': css})
            elif isinstance(w, DateInput):
                field.widget = DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': css})
            elif isinstance(w, Textarea):
                field.widget = Textarea(attrs={'class': f'{css} resize-none', 'rows': 4})
            elif isinstance(w, CheckboxInput):
                field.widget.attrs['class'] = 'w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500'
            elif isinstance(w, (TextInput, EmailInput, URLInput, NumberInput)):
                field.widget.attrs['class'] = css


class TableForm(ModelForm, TailwindForm):
    class Meta:
        model = Table
        exclude = ['slug', 'author', 'players', 'status', 'leaderboard_status']
        widgets = {
            'location': HiddenInput(),
            'games': autocomplete.ModelSelect2Multiple(
                url='games-autocomplete',
                attrs={'data-placeholder': _('Games')},
            ),
            'game': autocomplete.ModelSelect2(
                url='games-autocomplete',
                attrs={'data-placeholder': _('Game')},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].input_formats = ['%Y-%m-%d']

    def clean_title(self):
        title = self.cleaned_data['title']
        if title is None or len(title) < 2:
            raise ValidationError("Title is too short")
        return title

    def clean_description(self):
        description = self.cleaned_data['description']
        if description is None or len(description) < 2:
            raise ValidationError("Description is too short")
        return description

    def clean(self):
        cleaned_data = super().clean()
        min_players = cleaned_data.get('min_players')
        max_players = cleaned_data.get('max_players')
        if min_players and max_players and max_players < min_players:
            raise ValidationError(_("Maximum players cannot be less than minimum players."))
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
            self.save_m2m()
        return instance



class CommentForm(ModelForm, TailwindForm):
    class Meta:
        model = Comment
        fields = ['content']
        labels = {
            'content': _('Your comment...'),
        }


class CustomLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super(CustomLoginForm, self).__init__(*args, **kwargs)
        self.fields['username'].widget = CustomTextInputWidget()
        self.fields['username'].label = "Email"
        self.fields['password'].widget = CustomPasswordInputWidget()


class CustomPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super(CustomPasswordResetForm, self).__init__(*args, **kwargs)
        self.fields['email'].widget = CustomEmailWidget()


class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super(CustomSetPasswordForm, self).__init__(*args, **kwargs)
        self.fields['new_password1'].widget = CustomPasswordInputWidget()
        self.fields['new_password2'].widget = CustomPasswordInputWidget()


class UserRegistrationForm(UserCreationForm, TailwindForm):
    nickname = CharField(max_length=255)
    address = CharField(max_length=255)
    city = CharField(widget=HiddenInput(), required=False)
    latitude = CharField(widget=HiddenInput(), required=False)
    longitude = CharField(widget=HiddenInput(), required=False)

    captcha = ReCaptchaField(widget=ReCaptchaV2Checkbox)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_attrs = {'required': 'required', 'type': "text", 'class': "form-control"}
        self.fields['email'].widget.attrs.update({**base_attrs, 'placeholder': 'nome@email.com'})

        # Controlla se il form è stato inviato e se ci sono errori, per aggiungere la classe 'is-invalid'
        if self.is_bound:
            for field_name, field in self.fields.items():
                if field_name in self.errors:  # Controlla se il campo ha degli errori
                    css_classes = self.fields[field_name].widget.attrs.get('class', '')
                    if 'is-invalid' not in css_classes:
                        self.fields[field_name].widget.attrs['class'] = f'{css_classes} is-invalid'

    class Meta:
        model = User
        fields = ['email', 'password1', 'password2', 'nickname', 'address', 'city', 'latitude', 'longitude', 'captcha']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise ValidationError(_("Email already registered."))
        return email

    def clean_nickname(self):
        nickname = self.cleaned_data['nickname']
        if nickname is None:
            raise ValidationError(_(f"Insert nickname"))
        if nickname and UserProfile.objects.filter(nickname=nickname).exists():
            raise ValidationError(_("Profile with this Nickname already exists."))
        if len(nickname) > 25:
            raise ValidationError(_(f"Nickname can have at most 25 characters (it has {len(nickname)})."))
        return nickname

    def save(self, commit=True):
        if not commit:
            raise NotImplementedError("Can't create User and UserProfile without database save")

        user = super(UserRegistrationForm, self).save(commit=False)
        user.username = self.cleaned_data['email']

        if commit:
            user.save()

        user_profile = UserProfile(
            user=user,
            nickname=self.cleaned_data['nickname'],
            address=self.cleaned_data['address'],
            city=self.cleaned_data['city'],
            latitude=self.cleaned_data['latitude'],
            longitude=self.cleaned_data['longitude'],
        )
        user_profile.save()

        # location = Location(
        #     name="Default Location",
        #     creator=user_profile,
        #     description=f"#{self.cleaned_data['nickname']} Default Location",
        #     address=self.cleaned_data['address'],
        #     city=self.cleaned_data['city'],
        #     latitude=self.cleaned_data['latitude'],
        #     longitude=self.cleaned_data['longitude'],
        #     is_public=False,
        # )
        # location.save()

        return user, user_profile



class UserProfileForm(ModelForm, TailwindForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['city'].widget = HiddenInput()
        self.fields['latitude'].widget = HiddenInput()
        self.fields['longitude'].widget = HiddenInput()

    class Meta:
        model = UserProfile
        fields = ['nickname', 'address', 'city', 'latitude', 'longitude']


class UserProfileAvatarForm(ModelForm, TailwindForm):
    class Meta:
        model = UserProfile
        fields = ['avatar']


class LocationForm(ModelForm, TailwindForm):
    city = CharField(widget=HiddenInput(), required=False)
    latitude = CharField(widget=HiddenInput(), required=False)
    longitude = CharField(widget=HiddenInput(), required=False)

    class Meta:
        model = Location
        fields = ['name', 'creator', 'cover', 'description', 'address', 'city', 'latitude', 'longitude', 'website', 'is_public']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['creator'].widget = HiddenInput()
        self.fields['cover'].required = False
        self.fields['cover'].widget = FileInput(attrs={'class': 'hidden'})


class ContactForm(TailwindForm):
    name = CharField(
        label='Nome',
        max_length=100,
        widget=CustomTextInputWidget(placeholder="Nome")
    )
    email = EmailField(
        label='Email',
        widget=CustomEmailWidget(placeholder="nome@esempio.com")
    )
    message = CharField(
        label='Messaggio',
        widget=CustomTextareaWidget(placeholder="Scrivi il tuo messaggio qui...")
    )
    captcha = ReCaptchaField(widget=ReCaptchaV2Checkbox)


class UserNotificationPreferencesForm(ModelForm, TailwindForm):

    class Meta:
        model = UserProfile
        fields = [
            'notification_new_table',
            'notification_new_player',
            'notification_new_comments',
            'notification_leaderboard_reminder',
            'notification_leaderboard_update',
        ]


class AddLocationManagerForm(TailwindForm):
    """Form for adding a manager to a location"""
    manager = ModelChoiceField(
        queryset=UserProfile.objects.all(),
        label=_('Manager'),
        widget=autocomplete.ModelSelect2(
            url='userprofile-autocomplete',
            attrs={
                'data-placeholder': _('Search by username...'),
                'data-minimum-input-length': 1,
            }
        )
    )


class TransferOwnershipForm(TailwindForm):
    """Form for transferring location ownership"""
    new_owner = ModelChoiceField(
        queryset=UserProfile.objects.all(),
        label=_('New Owner'),
        widget=autocomplete.ModelSelect2(
            url='userprofile-autocomplete',
            attrs={
                'data-placeholder': _('Search by username...'),
                'data-minimum-input-length': 1,
            }
        )
    )
    add_as_manager = BooleanField(
        required=False,
        label=_('Add me as manager after transfer'),
        widget=CustomCheckboxInputWidget()
    )


class AddTablePlayerForm(TailwindForm):
    """Form for adding a player to a table"""
    player = ModelChoiceField(
        queryset=UserProfile.objects.all(),
        label=_('Gamer'),
        widget=autocomplete.ModelSelect2(
            url='userprofile-autocomplete',
            attrs={
                'data-placeholder': _('Search by username...'),
                'data-minimum-input-length': 1,
                'data-width': '100%',
            }
        )
    )



class MemberForm(ModelForm, TailwindForm):
    """Tailwind-styled version of MemberForm for the v2 UI."""
    user_profile = ModelChoiceField(
        queryset=UserProfile.objects.all(),
        required=False,
        label=_('Linked User Profile'),
        widget=autocomplete.ModelSelect2(
            url='userprofile-autocomplete',
            attrs={
                'data-placeholder': _('Search by username...'),
                'data-minimum-input-length': 1,
            }
        )
    )

    class Meta:
        from webapp.models import Member
        model = Member
        fields = ['first_name', 'last_name', 'code', 'email', 'phone_number', 'user_profile']


class MembershipRequestForm(TailwindForm):
    """Form for a logged-in user to request a membership for a location."""
    notes = CharField(
        required=False,
        label=_('Notes'),
        widget=CustomTextareaWidget(placeholder=_('Optional message to the manager...')),
    )


class ApproveMembershipForm(TailwindForm):
    """Form for a manager to approve a membership, setting start/end dates."""
    start_date = CharField(
        label=_('Start Date'),
        widget=CustomDateInputWidget(),
    )
    end_date = CharField(
        label=_('End Date'),
        widget=CustomDateInputWidget(),
    )
    notes = CharField(
        required=False,
        label=_('Notes'),
        widget=CustomTextareaWidget(),
    )


class MembershipEditForm(TailwindForm):
    """Form for a manager to edit an existing membership."""
    status = ChoiceField(
        label=_('Status'),
        choices=[],  # will be set in __init__
        widget=CustomSelectWidget(),
    )
    start_date = CharField(
        required=False,
        label=_('Start Date'),
        widget=CustomDateInputWidget(),
    )
    end_date = CharField(
        required=False,
        label=_('End Date'),
        widget=CustomDateInputWidget(),
    )
    notes = CharField(
        required=False,
        label=_('Notes'),
        widget=CustomTextareaWidget(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from webapp.models import Membership
        self.fields['status'].choices = Membership.STATUS_CHOICES


_TW_SELECT = (
    'w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 '
    'focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 '
    'bg-white transition-colors'
)


class LocationGameForm(ModelForm, TailwindForm):
    """Form to add/edit a game in a location's library."""
    game = ModelChoiceField(
        queryset=Game.objects.all(),
        label=_('Game'),
        widget=autocomplete.ModelSelect2(
            url='games-autocomplete',
            attrs={
                'data-placeholder': _('Search for a game...'),
                'data-minimum-input-length': 1,
            }
        )
    )

    class Meta:
        model = LocationGame
        fields = ['game', 'ownership', 'owner_member', 'physical_location', 'notes']

    def __init__(self, *args, location=None, **kwargs):
        super().__init__(*args, **kwargs)
        membership_enabled = bool(location and location.enable_membership)

        # owner_member is always visible; set required=False (FK is nullable)
        self.fields['owner_member'].required = False

        if membership_enabled:
            # Swap in the autocomplete widget scoped to this location.
            # Built here (not at class level) to avoid TailwindForm triggering
            # reverse() on a URL that requires args.
            url = reverse('member-autocomplete', kwargs={'location_slug': location.slug})
            self.fields['owner_member'] = ModelChoiceField(
                queryset=Member.objects.filter(location=location),
                required=False,
                label=_('Owner Member'),
                widget=autocomplete.ModelSelect2(
                    url=url,
                    attrs={
                        'data-placeholder': _('Search for a member...'),
                        'data-minimum-input-length': 1,
                    }
                )
            )
        else:
            # Membership not enabled: field is shown but fully disabled.
            # Widget rendering is handled in the template to match Select2 appearance.
            if location:
                self.fields['owner_member'].queryset = Member.objects.filter(location=location)
            self.fields['owner_member'].disabled = True

        # Apply Tailwind classes to Select widgets (TailwindForm skips them)
        for fn in ('ownership', 'physical_location'):
            self.fields[fn].widget.attrs['class'] = _TW_SELECT

    def clean(self):
        cleaned = super().clean()
        # When the game belongs to the location, no member owner makes sense
        if cleaned.get('ownership') == LocationGame.OWNED_BY_LOCATION:
            cleaned['owner_member'] = None
        return cleaned


class GuestProfileForm(ModelForm):
    name = CharField(
        widget=TextInput(attrs={
            'placeholder': _("Guest name"),
            'class': 'w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 bg-white transition-colors',
        }),
        label=_("Name"),
        max_length=100,
    )

    class Meta:
        model = GuestProfile
        fields = ['name']
