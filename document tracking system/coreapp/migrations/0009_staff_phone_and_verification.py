from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0008_rolepermission"),
    ]

    operations = [
        migrations.AddField(
            model_name="staff",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="staff",
            name="phone_number",
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="staff",
            name="phone_verified",
            field=models.BooleanField(default=False),
        ),
    ]
