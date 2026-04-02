from django.contrib import admin
from .models import Staff, Document, DocumentRouting, StaffMessage, StaffMessageRecipient, Notification, SystemPreference

admin.site.register(Staff)
admin.site.register(Document)
admin.site.register(DocumentRouting)
admin.site.register(StaffMessage)
admin.site.register(StaffMessageRecipient)
admin.site.register(Notification)
admin.site.register(SystemPreference)
