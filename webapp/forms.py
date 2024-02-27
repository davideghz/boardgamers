from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import ModelForm, CharField, TextInput, PasswordInput, Textarea, \
    Select, Form, EmailInput, NumberInput, DateInput, TimeInput, FileInput, HiddenInput, CheckboxInput
from webapp.models import Table, UserProfile, Comment, Player, Location

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


class CustomNumberWidget(NumberInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={'class': 'form-control', 'placeholder': placeholder, **(attrs or {})})


class CustomDateInputWidget(DateInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={
            'type': 'date',
            'class': 'form-control date-input',
            'placeholder': placeholder, **(attrs or {})})


class CustomTimeInputWidget(TimeInput):
    def __init__(self, attrs=None, placeholder="", time_format='%H:%M'):
        super().__init__(attrs={
            'type': 'time',
            'class': 'form-control time-input',
            'placeholder': placeholder,
            **(attrs or {})
        }, format=time_format)


class CustomFileInputWidget(FileInput):
    def __init__(self, attrs=None, placeholder=""):
        super().__init__(attrs={
            'class': 'form-control',
            'placeholder': placeholder,
            'autocomplete': 'new-password', **(attrs or {})})


class CustomCheckboxInputWidget(CheckboxInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={
            'class': 'form-check-input',
            'role': 'switch',
            'autocomplete': 'new-password', **(attrs or {})})


class BootstrapForm(Form):
    def __init__(self, *args, **kwargs):
        super(Form, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, TimeInput):
                field.widget = CustomTimeInputWidget()
            elif isinstance(field.widget, DateInput):
                field.widget = CustomDateInputWidget()
            elif isinstance(field.widget, TextInput):
                field.widget = CustomTextInputWidget()
            elif isinstance(field.widget, PasswordInput):
                field.widget = CustomPasswordInputWidget()
            elif isinstance(field.widget, Textarea):
                field.widget = CustomTextareaWidget()
            # elif isinstance(field.widget, Select):
            #     field.widget = CustomSelectWidget(choices=field.choices)
            elif isinstance(field.widget, EmailInput):
                field.widget = CustomEmailWidget()
            elif isinstance(field.widget, NumberInput):
                field.widget = CustomNumberWidget()
            elif isinstance(field.widget, FileInput):
                field.widget = CustomFileInputWidget()
            elif isinstance(field.widget, CheckboxInput):
                field.widget = CustomCheckboxInputWidget()

            if self.errors.get(field_name):
                if 'class' in field.widget.attrs:
                    field.widget.attrs['class'] += ' is-invalid'
                else:
                    field.widget.attrs['class'] = 'is-invalid'


class TableForm(ModelForm, BootstrapForm):
    class Meta:
        model = Table
        exclude = ['slug', 'author']
        widgets = {
            'location': autocomplete.ModelSelect2(
                url='location-autocomplete',
                forward=['is_public_location'],
                attrs={
                    'data-placeholder': _('Select Location'),
                    # 'data-minimum-input-length': 3
                }),
            'games': autocomplete.ModelSelect2Multiple(
                url='games-autocomplete',
                attrs={
                    'data-placeholder': _('Games'),
                    # 'data-minimum-input-length': 1
                }),
        }

    def clean_title(self):
        title = self.cleaned_data['title']
        if title is None or len(title) < 10:
            raise ValidationError("Title is too short")
        return title

    def clean_description(self):
        description = self.cleaned_data['description']
        if description is None or len(description) < 30:
            raise ValidationError("Description is too short")
        return description


class CommentForm(ModelForm, BootstrapForm):
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


class UserRegistrationForm(UserCreationForm, BootstrapForm):
    nickname = CharField(max_length=255)
    address = CharField(max_length=255)
    city = CharField(widget=HiddenInput(), required=False)
    latitude = CharField(widget=HiddenInput(), required=False)
    longitude = CharField(widget=HiddenInput(), required=False)

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
        fields = ['email', 'password1', 'password2', 'nickname', 'address', 'city', 'latitude', 'longitude']

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

        location = Location(
            name="Default Location",
            creator=user_profile,
            description=f"#{self.cleaned_data['nickname']} Default Location",
            address=self.cleaned_data['address'],
            city=self.cleaned_data['city'],
            latitude=self.cleaned_data['latitude'],
            longitude=self.cleaned_data['longitude'],
            is_public=False,
        )
        location.save()

        return user, user_profile


class UserProfileForm(ModelForm, BootstrapForm):
    city = CharField(widget=HiddenInput(), required=False, )
    latitude = CharField(widget=HiddenInput(), required=False, )
    longitude = CharField(widget=HiddenInput(), required=False, )

    class Meta:
        model = UserProfile
        fields = ['nickname', 'address', 'city', 'latitude', 'longitude']


class UserProfileAvatarForm(ModelForm, BootstrapForm):
    class Meta:
        model = UserProfile
        fields = ['avatar']


class JoinTableForm(ModelForm, BootstrapForm):
    class Meta:
        model = Player
        fields = []


class LocationForm(ModelForm, BootstrapForm):
    city = CharField(widget=HiddenInput(), required=False)
    latitude = CharField(widget=HiddenInput(), required=False)
    longitude = CharField(widget=HiddenInput(), required=False)

    class Meta:
        model = Location
        fields = ['name', 'creator', 'description', 'address', 'city', 'latitude', 'longitude', 'is_public']
