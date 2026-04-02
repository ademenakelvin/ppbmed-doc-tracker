from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0010_remove_staff_verification_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="department",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="staff",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staff",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
    ]
