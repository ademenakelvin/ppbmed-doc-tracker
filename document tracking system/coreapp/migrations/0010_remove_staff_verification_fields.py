from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0009_staff_phone_and_verification"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="staff",
            name="email_verified",
        ),
        migrations.RemoveField(
            model_name="staff",
            name="phone_number",
        ),
        migrations.RemoveField(
            model_name="staff",
            name="phone_verified",
        ),
    ]
