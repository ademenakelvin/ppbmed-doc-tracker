from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.forms import BaseFormSet, formset_factory, inlineformset_factory

from .models import Booking, Inventory, Payment, PriceOption, RentalItem

User = get_user_model()


class StyledFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "form-control"
                widget.attrs.setdefault("rows", 4)
            else:
                widget.attrs["class"] = "form-control"


class LoginForm(StyledFieldsMixin, AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"placeholder": "Staff username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Password"}))


class RentalItemForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = RentalItem
        fields = ["category", "name", "is_active"]


class InventoryForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ["quantity_total", "quantity_available"]
        widgets = {
            "quantity_total": forms.NumberInput(attrs={"min": 0}),
            "quantity_available": forms.NumberInput(attrs={"min": 0}),
        }


class PriceOptionForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = PriceOption
        fields = ["label", "amount", "is_default", "is_active"]
        widgets = {"amount": forms.NumberInput(attrs={"step": "0.01", "min": 0})}


PriceOptionFormSet = inlineformset_factory(
    RentalItem,
    PriceOption,
    form=PriceOptionForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class BookingCreateForm(StyledFieldsMixin, forms.ModelForm):
    customer_name = forms.CharField(max_length=150)
    customer_phone = forms.CharField(max_length=30)

    class Meta:
        model = Booking
        fields = ["event_date", "return_due_date", "notes"]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "return_due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"placeholder": "Optional operational notes"}),
        }


class RentalItemChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} (Stock: {obj.quantity_total}, Available now: {obj.quantity_available})"


class PriceOptionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.rental_item.name} - {obj.label} (GHS {obj.amount:.2f}/day)"


class BookingItemForm(StyledFieldsMixin, forms.Form):
    rental_item = RentalItemChoiceField(queryset=RentalItem.objects.filter(is_active=True).select_related("category"))
    price_option = PriceOptionChoiceField(queryset=PriceOption.objects.filter(is_active=True).select_related("rental_item"))
    quantity = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"min": 1}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            item_id = self.data.get(self.add_prefix("rental_item"))
            if item_id:
                self.fields["price_option"].queryset = PriceOption.objects.filter(
                    rental_item_id=item_id,
                    is_active=True,
                ).select_related("rental_item")

    def clean(self):
        cleaned_data = super().clean()
        rental_item = cleaned_data.get("rental_item")
        price_option = cleaned_data.get("price_option")
        if rental_item and price_option and price_option.rental_item_id != rental_item.id:
            self.add_error("price_option", "Choose a price option that belongs to the selected item.")
        return cleaned_data


class BaseBookingItemFormSet(BaseFormSet):
    def __init__(self, *args, event_date=None, return_due_date=None, booking=None, **kwargs):
        self.event_date = event_date
        self.return_due_date = return_due_date
        self.booking = booking
        super().__init__(*args, **kwargs)

    def clean(self):
        if any(self.errors):
            return

        total_rows = 0
        requested_quantities = {}
        for form in self.forms:
            if not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            rental_item = form.cleaned_data.get("rental_item")
            quantity = form.cleaned_data.get("quantity")
            if not rental_item or not quantity:
                continue

            total_rows += 1
            requested_quantities[rental_item] = requested_quantities.get(rental_item, 0) + quantity

        if total_rows == 0:
            raise forms.ValidationError("Every booking must include at least one item.")

        if not self.event_date or not self.return_due_date:
            return

        for rental_item, quantity in requested_quantities.items():
            inventory = Inventory.objects.get(rental_item=rental_item)
            available = inventory.available_for_range(
                self.event_date,
                self.return_due_date,
                exclude_booking=self.booking,
            )
            if quantity > available:
                raise forms.ValidationError(
                    f"Only {available} unit(s) of {rental_item.name} are available for the selected dates."
                )


BookingItemFormSet = formset_factory(
    BookingItemForm,
    formset=BaseBookingItemFormSet,
    extra=1,
    can_delete=True,
)


class PaymentForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "notes"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": 0.01}),
            "paid_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"placeholder": "Optional payment note"}),
        }


class StaffAccountForm(StyledFieldsMixin, forms.ModelForm):
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Temporary password"}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Repeat password"}))

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_booking_approver"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Staff username"}),
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "Email address"}),
        }

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")

        if password1 != password2:
            raise forms.ValidationError("The two password fields must match.")

        validate_password(password2)
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STAFF
        user.is_staff = False
        user.is_superuser = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class StaffAccountUpdateForm(StyledFieldsMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_booking_approver", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Staff username"}),
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "Email address"}),
        }
