NOTIFICATION_KIND_LABELS = {
    "booking": "Booking updates",
    "payment": "Payment reminders",
    "inventory": "Inventory alerts",
    "returns": "Return alerts",
    "general": "General alerts",
}


GENERAL_NOTIFICATION_KIND_LABELS = {
    key: label for key, label in NOTIFICATION_KIND_LABELS.items() if key != "inventory"
}


def notification_kind(notification):
    title = notification.title.lower()
    message = notification.message.lower()
    combined = f"{title} {message}"

    if "payment" in combined or "balance" in combined:
        return "payment"
    if "stock" in combined or "inventory" in combined:
        return "inventory"
    if "return" in combined:
        return "returns"
    if notification.booking_id:
        return "booking"
    return "general"


def attach_notification_kinds(notifications):
    notifications = list(notifications)
    for notification in notifications:
        notification.kind = notification_kind(notification)
    return notifications


def filter_notifications(notifications, *, scope="all", state="all", kind="all"):
    notifications = attach_notification_kinds(notifications)

    if scope == "inventory":
        notifications = [note for note in notifications if note.kind == "inventory"]
    elif scope == "general":
        notifications = [note for note in notifications if note.kind != "inventory"]

    if state == "unread":
        notifications = [note for note in notifications if not note.is_read]
    elif state == "read":
        notifications = [note for note in notifications if note.is_read]

    if kind != "all":
        notifications = [note for note in notifications if note.kind == kind]

    return notifications


def group_notifications(notifications, labels):
    groups = []
    for kind_key, kind_label in labels.items():
        grouped_items = [note for note in notifications if note.kind == kind_key]
        if grouped_items:
            groups.append({"key": kind_key, "label": kind_label, "items": grouped_items})
    return groups
