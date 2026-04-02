from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    ActivityLog,
    Booking,
    BookingItem,
    Category,
    Customer,
    Inventory,
    Notification,
    Payment,
    PriceOption,
    RentalItem,
    User,
)


admin.site.site_header = "WINBIRD Enterprise Admin"
admin.site.site_title = "WINBIRD Admin"
admin.site.index_title = "Internal rental operations"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("WINBIRD Access", {"fields": ("role",)}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


class PriceOptionInline(admin.TabularInline):
    model = PriceOption
    extra = 1


class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0
    max_num = 1


@admin.register(RentalItem)
class RentalItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "quantity_total", "quantity_available")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    inlines = [InventoryInline, PriceOptionInline]

    @admin.display(ordering="inventory__quantity_total")
    def quantity_total(self, obj):
        return obj.quantity_total

    @admin.display(ordering="inventory__quantity_available")
    def quantity_available(self, obj):
        return obj.quantity_available


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "created_at")
    search_fields = ("name", "phone")


class BookingItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "event_date", "return_due_date", "status", "payment_status", "created_by")
    list_filter = ("status", "payment_status", "event_date")
    search_fields = ("customer__name", "customer__phone")
    readonly_fields = ("created_at", "updated_at", "approved_at", "dispatched_at", "returned_at", "completed_at")
    inlines = [BookingItemInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("booking", "amount", "paid_on", "recorded_by")
    list_filter = ("paid_on",)
    search_fields = ("booking__customer__name", "booking__customer__phone")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "booking", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("title", "message")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "booking", "user", "created_at")
    search_fields = ("action", "booking__customer__name", "user__username")

# Register your models here.
