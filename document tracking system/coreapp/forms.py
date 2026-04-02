from pathlib import Path

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import Staff, Document, DocumentRouting, StaffMessage, SystemPreference


MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {
    '.pdf',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.bmp',
    '.doc',
    '.docx',
    '.txt',
    '.csv',
    '.xls',
    '.xlsx',
    '.ppt',
    '.pptx',
    '.zip',
}
ALLOWED_UPLOAD_CONTENT_TYPES = {
    'application/pdf',
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/bmp',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/zip',
    'application/x-zip-compressed',
}
UPLOAD_ACCEPT_ATTR = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.bmp,.doc,.docx,.txt,.csv,.xls,.xlsx,.ppt,.pptx,.zip"


def validate_uploaded_file(uploaded_file):
    if not uploaded_file:
        return

    extension = Path(uploaded_file.name).suffix.lower()
    content_type = getattr(uploaded_file, 'content_type', '')

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError('File is too large. Maximum allowed size is 10 MB.')

    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError('Unsupported file type. Allowed types: PDF, PNG, JPG, JPEG, GIF, WEBP, BMP, DOC, DOCX, TXT, CSV, XLS, XLSX, PPT, PPTX, ZIP.')

    if content_type and content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise ValidationError('The uploaded file type is not allowed.')


class StaffForm(forms.ModelForm):
    create_login_account = forms.BooleanField(
        required=False,
        label="Create login account for this staff member"
    )
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'})
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'})
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'})
    )

    class Meta:
        model = Staff
        fields = ['user', 'full_name', 'role', 'department', 'email', 'is_active']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter full name'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter department'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'staff-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and self.instance.user:
            self.fields['user'].queryset = User.objects.filter(pk=self.instance.user.pk) | User.objects.filter(staff_profile__isnull=True)
        else:
            self.fields['user'].queryset = User.objects.filter(staff_profile__isnull=True)

        self.fields['user'].required = False
        self.fields['user'].empty_label = "Select existing Django user"
        self.fields['email'].required = True

    def clean(self):
        cleaned_data = super().clean()
        create_login_account = cleaned_data.get('create_login_account')
        selected_user = cleaned_data.get('user')
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        email = cleaned_data.get('email')

        if create_login_account and selected_user:
            raise forms.ValidationError("Choose either an existing Django user or create a new login account, not both.")

        if create_login_account:
            if not username:
                self.add_error('username', 'Username is required when creating a login account.')
            if not password:
                self.add_error('password', 'Password is required when creating a login account.')
            if not confirm_password:
                self.add_error('confirm_password', 'Please confirm the password.')
            if password and confirm_password and password != confirm_password:
                self.add_error('confirm_password', 'Passwords do not match.')
            if username and User.objects.filter(username=username).exists():
                self.add_error('username', 'This username already exists.')
            if email and User.objects.filter(email=email).exists():
                self.add_error('email', 'A Django user with this email already exists.')
            if username and password:
                temp_user = User(username=username, email=email or '')
                try:
                    validate_password(password, user=temp_user)
                except ValidationError as exc:
                    self.add_error('password', exc)

        return cleaned_data


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            'reference_id',
            'subject',
            'description',
            'direction',
            'document_type',
            'department',
            'origin',
            'destination',
            'assigned_to',
            'priority',
            'status',
            'date_received',
            'due_date',
            'attachment',
        ]
        widgets = {
            'reference_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter reference ID'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter subject'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter description', 'rows': 4}),
            'direction': forms.Select(attrs={'class': 'form-control'}),
            'document_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter document type'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter owning department'}),
            'origin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter origin'}),
            'destination': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter destination'}),
            'assigned_to': forms.Select(attrs={'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'date_received': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = Staff.objects.filter(is_active=True).order_by('full_name')
        self.fields['assigned_to'].empty_label = "Select officer"
        self.fields['department'].required = False

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        validate_uploaded_file(attachment)
        return attachment


class DocumentRoutingForm(forms.ModelForm):
    class Meta:
        model = DocumentRouting
        fields = ['from_officer', 'to_officer', 'action', 'note', 'attachment']
        widgets = {
            'from_officer': forms.Select(attrs={'class': 'form-control'}),
            'to_officer': forms.Select(attrs={'class': 'form-control'}),
            'action': forms.Select(attrs={'class': 'form-control'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter note or instruction', 'rows': 4}),
            'attachment': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_staff = Staff.objects.filter(is_active=True).order_by('full_name')
        self.fields['from_officer'].queryset = active_staff
        self.fields['to_officer'].queryset = active_staff
        self.fields['from_officer'].empty_label = "Select sender"
        self.fields['to_officer'].empty_label = "Select receiver"

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        attachment = cleaned_data.get('attachment')

        if action == "Returned" and not attachment:
            self.add_error('attachment', 'Attachment is required when returning a document.')

        return cleaned_data

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        validate_uploaded_file(attachment)
        return attachment


class MessageComposeForm(forms.ModelForm):
    recipients = forms.ModelMultipleChoiceField(
        queryset=Staff.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 8}),
        required=True,
        help_text="Choose the staff who should receive the message.",
    )

    class Meta:
        model = StaffMessage
        fields = ['subject', 'body', 'attachment', 'recipients']
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter message subject'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Write your message', 'rows': 6}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': UPLOAD_ACCEPT_ATTR}),
        }

    def __init__(self, *args, sender=None, **kwargs):
        super().__init__(*args, **kwargs)
        recipients_qs = Staff.objects.filter(is_active=True, is_archived=False).order_by('full_name')
        if sender and sender.pk:
            recipients_qs = recipients_qs.exclude(pk=sender.pk)
        self.fields['recipients'].queryset = recipients_qs
        self.sender = sender

    def clean(self):
        cleaned_data = super().clean()
        recipients = cleaned_data.get('recipients')
        body = (cleaned_data.get('body') or '').strip()
        attachment = cleaned_data.get('attachment')

        if recipients is not None and not recipients:
            self.add_error('recipients', 'Choose at least one staff member to receive the message.')

        cleaned_data['body'] = body

        if not body and not attachment:
            self.add_error('body', 'Enter a message or attach a file.')

        return cleaned_data

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        validate_uploaded_file(attachment)
        return attachment


class MessageReplyForm(forms.Form):
    body = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Write your reply', 'rows': 4})
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': UPLOAD_ACCEPT_ATTR})
    )

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        validate_uploaded_file(attachment)
        return attachment

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get('body') or '').strip()
        attachment = cleaned_data.get('attachment')

        cleaned_data['body'] = body

        if not body and not attachment:
            raise ValidationError('Enter a message or attach a file.')

        return cleaned_data


class ProfileSettingsForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ['full_name', 'email', 'department']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
        }


class PreferenceSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemPreference
        fields = ['email_notifications', 'sound_alerts', 'dark_mode']


class PasswordChangeCustomForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Current password'})
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New password'})
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm new password'})
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise forms.ValidationError("Current password is incorrect.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error('confirm_password', 'New passwords do not match.')

        if new_password:
            try:
                validate_password(new_password, user=self.user)
            except ValidationError as exc:
                self.add_error('new_password', exc)

        return cleaned_data
