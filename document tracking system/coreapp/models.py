from datetime import date
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Staff(models.Model):
    ROLE_CHOICES = [
        ('Director', 'Director'),
        ('Deputy Director', 'Deputy Director'),
        ('Staff', 'Staff'),
        ('Registry', 'Registry'),
        ('Admin', 'Admin'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='staff_profile'
    )
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='Staff')
    department = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.role})"


class Document(models.Model):
    DIRECTION_CHOICES = [
        ('Incoming', 'Incoming'),
        ('Outgoing', 'Outgoing'),
    ]

    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Overdue', 'Overdue'),
    ]

    reference_id = models.CharField(max_length=50, unique=True)
    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default='Incoming')
    document_type = models.CharField(max_length=100, blank=True, null=True)

    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    assigned_to = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='assigned_documents'
    )

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='Medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

    date_received = models.DateField()
    due_date = models.DateField(blank=True, null=True)

    attachment = models.FileField(upload_to='documents/', blank=True, null=True)
    department = models.CharField(max_length=255, blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.due_date and self.due_date < date.today() and self.status != "Completed":
            self.status = "Overdue"
        super().save(*args, **kwargs)

    def archive(self):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def restore(self):
        self.is_archived = False
        self.archived_at = None
        self.save(update_fields=['is_archived', 'archived_at'])

    def __str__(self):
        return f"{self.reference_id} - {self.subject}"


class DocumentRouting(models.Model):
    ACTION_CHOICES = [
        ('Assigned', 'Assigned'),
        ('Forwarded', 'Forwarded'),
        ('Returned', 'Returned'),
        ('Completed', 'Completed'),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='routing_history')
    from_officer = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='routed_from_records'
    )
    to_officer = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='routed_to_records'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    note = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='routing_attachments/', blank=True, null=True)
    action_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-action_date']

    def __str__(self):
        to_name = self.to_officer.full_name if self.to_officer else "Unknown"
        return f"{self.document.reference_id} - {self.action} to {to_name}"


class StaffMessage(models.Model):
    sender = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    attachment = models.FileField(upload_to='message_attachments/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} ({self.sender.full_name})"


class StaffMessageRecipient(models.Model):
    staff_message = models.ForeignKey(
        StaffMessage,
        on_delete=models.CASCADE,
        related_name='recipient_links'
    )
    recipient = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name='received_messages'
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-staff_message__created_at']
        unique_together = ('staff_message', 'recipient')

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def __str__(self):
        return f"{self.recipient.full_name} - {self.staff_message.subject}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('assignment', 'Assignment'),
        ('forwarded', 'Forwarded'),
        ('returned', 'Returned'),
        ('completed', 'Completed'),
        ('overdue', 'Overdue'),
        ('message', 'Message'),
        ('general', 'General'),
    ]

    recipient = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='notifications'
    )
    staff_message = models.ForeignKey(
        StaffMessage,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='notifications'
    )
    message = models.CharField(max_length=255)
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='general')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.full_name} - {self.message}"


class SystemPreference(models.Model):
    staff = models.OneToOneField(
        Staff,
        on_delete=models.CASCADE,
        related_name='preferences'
    )
    email_notifications = models.BooleanField(default=True)
    sound_alerts = models.BooleanField(default=True)
    dark_mode = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.staff.full_name}"


class LoginHistory(models.Model):
    EVENT_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
    ]

    staff = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='login_history'
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, default='login')
    username = models.CharField(max_length=150)
    role = models.CharField(max_length=50, blank=True)
    ip_address = models.CharField(max_length=100, blank=True)
    user_agent = models.TextField(blank=True)
    logged_in_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_in_at']
        verbose_name_plural = "Login history"

    def __str__(self):
        return f"{self.username} {self.event_type} at {self.logged_in_at:%Y-%m-%d %H:%M:%S}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_label = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} - {self.target_label}"


class RolePermission(models.Model):
    role = models.CharField(max_length=50, choices=Staff.ROLE_CHOICES)
    permission_key = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('role', 'permission_key')
        ordering = ['role', 'permission_key']

    def __str__(self):
        state = "Enabled" if self.enabled else "Disabled"
        return f"{self.role} - {self.permission_key} ({state})"


class ITMaintenanceLog(models.Model):
    category = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    details = models.TextField()
    logged_by = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='it_maintenance_logs'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.category} - {self.title}"
