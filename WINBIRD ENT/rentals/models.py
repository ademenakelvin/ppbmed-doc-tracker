from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        STAFF = "STAFF", "Staff"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    is_booking_approver = models.BooleanField(
        default=False,
        help_text="Allow this staff user to confirm bookings without full admin access.",
    )

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
            self.is_staff = True
            self.is_booking_approver = True
        elif self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_booking_approver = True
        super().save(*args, **kwargs)

    @property
    def can_confirm_bookings(self):
        return self.is_superuser or self.role == self.Role.ADMIN or self.is_booking_approver

    @property
    def can_approve_bookings(self):
        return self.can_confirm_bookings

    @property
    def can_cancel_bookings(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def can_manage_catalog(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    def __str__(self):
        return self.get_full_name().strip() or self.username


class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class RentalItem(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            Inventory.objects.get_or_create(
                rental_item=self,
                defaults={"quantity_total": 0, "quantity_available": 0},
            )

    @property
    def default_price_option(self):
        return self.price_options.filter(is_default=True, is_active=True).first() or self.price_options.filter(
            is_active=True
        ).first()

    @property
    def quantity_total(self):
        try:
            return self.inventory.quantity_total
        except Inventory.DoesNotExist:
            return 0

    @property
    def quantity_available(self):
        try:
            return self.inventory.quantity_available
        except Inventory.DoesNotExist:
            return 0

    def __str__(self):
        return self.name


class PriceOption(models.Model):
    rental_item = models.ForeignKey(RentalItem, on_delete=models.CASCADE, related_name="price_options")
    label = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rental_item__name", "amount", "label"]
        unique_together = ("rental_item", "label", "amount")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            self.rental_item.price_options.exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return f"{self.rental_item.name} - {self.label} (GHS {self.amount})"


class Inventory(models.Model):
    rental_item = models.OneToOneField(RentalItem, on_delete=models.CASCADE, related_name="inventory")
    quantity_total = models.PositiveIntegerField(default=0)
    quantity_available = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rental_item__name"]
        verbose_name_plural = "inventory"

    def clean(self):
        if self.quantity_available > self.quantity_total:
            raise ValidationError({"quantity_available": "Available quantity cannot exceed total quantity."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def reserved_quantity(self, start_date, end_date, exclude_booking=None):
        if not start_date or not end_date:
            return 0

        queryset = BookingItem.objects.filter(
            rental_item=self.rental_item,
            booking__status__in=Booking.active_statuses(),
            booking__event_date__lte=end_date,
            booking__return_due_date__gte=start_date,
        )
        if exclude_booking and exclude_booking.pk:
            queryset = queryset.exclude(booking=exclude_booking)
        return queryset.aggregate(total=Sum("quantity"))["total"] or 0

    def available_for_range(self, start_date, end_date, exclude_booking=None):
        reserved = self.reserved_quantity(start_date, end_date, exclude_booking=exclude_booking)
        return max(self.quantity_total - reserved, 0)

    def __str__(self):
        return f"{self.rental_item.name} inventory"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        RETURNED = "RETURNED", "Returned"
        COMPLETED = "COMPLETED", "Completed"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bookings")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_bookings")
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="approved_bookings",
        blank=True,
        null=True,
    )
    event_date = models.DateField()
    return_due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    dispatched_at = models.DateTimeField(blank=True, null=True)
    returned_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def active_statuses(cls):
        return [cls.Status.PENDING, cls.Status.CONFIRMED]

    def clean(self):
        if self.return_due_date < self.event_date:
            raise ValidationError({"return_due_date": "Return due date cannot be earlier than the event date."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def rental_days(self):
        if not self.event_date or not self.return_due_date:
            return 1
        return max((self.return_due_date - self.event_date).days + 1, 1)

    @property
    def total_amount(self):
        return sum((item.line_total for item in self.items.all()), Decimal("0.00"))

    @property
    def amount_paid(self):
        total = self.payments.aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    @property
    def balance_due(self):
        return max(self.total_amount - self.amount_paid, Decimal("0.00"))

    @property
    def can_be_completed(self):
        return self.status == self.Status.RETURNED

    def refresh_payment_status(self, commit=True):
        total = self.total_amount
        paid = self.amount_paid

        if paid <= Decimal("0.00"):
            self.payment_status = self.PaymentStatus.UNPAID
        elif paid < total:
            self.payment_status = self.PaymentStatus.PARTIAL
        else:
            self.payment_status = self.PaymentStatus.PAID

        if commit and self.pk:
            self.save(update_fields=["payment_status", "updated_at"])
        return self.payment_status

    def __str__(self):
        return f"Booking #{self.pk} - {self.customer.name}"


class BookingItem(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items")
    rental_item = models.ForeignKey(RentalItem, on_delete=models.PROTECT, related_name="booking_items")
    price_option = models.ForeignKey(PriceOption, on_delete=models.PROTECT, related_name="booking_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["rental_item__name"]

    def clean(self):
        errors = {}

        if self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.price_option_id and self.rental_item_id and self.price_option.rental_item_id != self.rental_item_id:
            errors["price_option"] = "Selected price option does not belong to the chosen rental item."

        if (
            self.booking_id
            and self.booking.status in Booking.active_statuses()
            and self.booking.event_date
            and self.booking.return_due_date
        ):
            try:
                inventory = Inventory.objects.get(rental_item=self.rental_item)
            except Inventory.DoesNotExist:
                errors["rental_item"] = "This item does not have an inventory record yet."
            else:
                available = inventory.available_for_range(
                    self.booking.event_date,
                    self.booking.return_due_date,
                    exclude_booking=self.booking,
                )
                if self.quantity > available:
                    errors["quantity"] = (
                        f"Only {available} unit(s) of {self.rental_item.name} are available for the selected dates."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.price_option_id and not self.unit_price:
            self.unit_price = self.price_option.amount
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def rental_days(self):
        if self.booking_id and self.booking.event_date and self.booking.return_due_date:
            return self.booking.rental_days
        return 1

    @property
    def line_total(self):
        return self.unit_price * self.quantity * self.rental_days

    def __str__(self):
        return f"{self.rental_item.name} x {self.quantity}"


class Payment(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField(default=timezone.localdate)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="payments_recorded")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-created_at"]

    def clean(self):
        if self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount must be greater than zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        response = super().save(*args, **kwargs)
        self.booking.refresh_payment_status()
        return response

    def __str__(self):
        return f"Payment for booking #{self.booking_id}"


class Notification(models.Model):
    title = models.CharField(max_length=150)
    message = models.TextField()
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="notifications",
        blank=True,
        null=True,
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ActivityLog(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="activity_logs",
        blank=True,
        null=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.action
