from django.core.exceptions import ValidationError

from .models import ActivityLog, Notification


def log_activity(user, action, booking=None):
    return ActivityLog.objects.create(user=user, booking=booking, action=action)


def create_notification(title, message, booking=None):
    return Notification.objects.create(title=title, message=message, booking=booking)


def dispatch_booking_items(booking):
    if booking.dispatched_at:
        raise ValidationError("This booking has already been marked as out.")

    for booking_item in booking.items.select_related("rental_item__inventory"):
        inventory = booking_item.rental_item.inventory
        if inventory.quantity_available < booking_item.quantity:
            raise ValidationError(
                f"Only {inventory.quantity_available} unit(s) of {booking_item.rental_item.name} are available right now."
            )

    for booking_item in booking.items.select_related("rental_item__inventory"):
        inventory = booking_item.rental_item.inventory
        inventory.quantity_available -= booking_item.quantity
        inventory.save(update_fields=["quantity_available", "updated_at"])
        if inventory.quantity_available == 0:
            create_notification(
                "Inventory alert",
                f"{booking_item.rental_item.name} is now out of stock after booking #{booking.pk} was dispatched.",
                booking=booking,
            )
        elif inventory.quantity_available <= 3:
            create_notification(
                "Low stock alert",
                f"{booking_item.rental_item.name} is running low with only {inventory.quantity_available} unit(s) left.",
                booking=booking,
            )


def return_booking_items(booking):
    if not booking.dispatched_at:
        raise ValidationError("Items must be marked as out before they can be returned.")

    for booking_item in booking.items.select_related("rental_item__inventory"):
        inventory = booking_item.rental_item.inventory
        inventory.quantity_available = min(
            inventory.quantity_total,
            inventory.quantity_available + booking_item.quantity,
        )
        inventory.save(update_fields=["quantity_available", "updated_at"])
