# Generated by Django 4.2.5 on 2023-09-21 13:14

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cwmessages', '0001_initial'),
        ('cwnotifications', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversationparticipant',
            name='notification_recipient',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='cwnotifications.notificationrecipient'),
        ),
    ]