from .models import Notification
from .notification_utils import filter_notifications


def notification_summary(request):
    if not request.user.is_authenticated:
        return {}

    unread_notifications = Notification.objects.filter(is_read=False)
    unread_notification_count = len(filter_notifications(unread_notifications, scope="general", state="unread"))
    unread_inventory_alert_count = len(filter_notifications(unread_notifications, scope="inventory", state="unread"))
    return {
        "unread_notification_count": unread_notification_count,
        "unread_inventory_alert_count": unread_inventory_alert_count,
    }
