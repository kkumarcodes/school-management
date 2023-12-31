# Generated by Django 4.2.5 on 2023-09-21 13:14

import sncommon.models
from django.conf import settings
import django.core.serializers.json
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('time_description', models.TextField(blank=True)),
                ('available', models.BooleanField(default=True)),
                ('display_on_landing_page', models.BooleanField(default=False)),
                ('category', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Diagnostic',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('diagnostic_type', models.CharField(choices=[('act', 'ACT'), ('act', 'Other'), ('sat', 'SAT'), ('math', 'Math'), ('science', 'Science'), ('writing', 'Writing')], max_length=100)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True)),
                ('form_specification', models.JSONField(blank=True, default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('can_self_assign', models.BooleanField(default=False)),
                ('archived', models.BooleanField(default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DiagnosticGroupTutoringSessionRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('registration_type', models.CharField(choices=[('act', 'ACT'), ('sat', 'SAT'), ('both', 'Both')], max_length=4)),
                ('registration_data', models.JSONField(default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DiagnosticResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('state', models.CharField(choices=[('ps', 'Pending Score'), ('pr', 'Pending Recommendation'), ('pe', 'Pending Return to Student'), ('v', 'Visible to Student')], default='ps', max_length=2)),
                ('submission_note', models.TextField(blank=True)),
                ('score', models.FloatField(blank=True, null=True)),
                ('feedback', models.TextField(blank=True)),
                ('admin_note', models.TextField(blank=True)),
                ('feedback_provided', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='GroupTutoringSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('set_charge_student_duration', models.IntegerField(blank=True, null=True)),
                ('set_pay_tutor_duration', models.IntegerField(blank=True, null=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('start', models.DateTimeField(blank=True, null=True)),
                ('end', models.DateTimeField(blank=True, null=True)),
                ('cancelled', models.BooleanField(default=False)),
                ('staff_note', models.TextField(blank=True)),
                ('capacity', models.SmallIntegerField(default=100)),
                ('include_in_catalog', models.BooleanField(default=True)),
                ('notes_skipped', models.BooleanField(default=False)),
                ('zoom_url', models.CharField(blank=True, max_length=255)),
                ('last_reminder_sent', models.DateTimeField(blank=True, null=True)),
                ('outlook_event_id', models.TextField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('address', models.CharField(blank=True, max_length=255)),
                ('address_line_two', models.CharField(blank=True, max_length=255)),
                ('city', models.CharField(blank=True, max_length=255)),
                ('zip_code', models.CharField(blank=True, max_length=11)),
                ('state', models.CharField(blank=True, max_length=2)),
                ('country', models.CharField(blank=True, default='United States', max_length=255)),
                ('set_timezone', models.CharField(blank=True, max_length=255)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('is_remote', models.BooleanField(default=False)),
                ('is_default_location', models.BooleanField(default=False)),
                ('default_zoom_url', models.TextField(blank=True)),
                ('offers_tutoring', models.BooleanField(default=True)),
                ('offers_admissions', models.BooleanField(default=False)),
                ('magento_id', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RecurringTutorAvailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('active', models.BooleanField(default=True)),
                ('availability', models.JSONField(default=sncommon.models.get_default_availability, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('locations', models.JSONField(default=sncommon.models.get_default_locations, encoder=django.core.serializers.json.DjangoJSONEncoder)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='StudentTutoringSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('session_type', models.CharField(choices=[('t', 'Test Prep'), ('c', 'Curriculum')], max_length=1)),
                ('start', models.DateTimeField(blank=True, null=True)),
                ('end', models.DateTimeField(blank=True, null=True)),
                ('duration_minutes', models.SmallIntegerField(default=60)),
                ('is_tentative', models.BooleanField(default=False)),
                ('note', models.TextField(blank=True)),
                ('notes_skipped', models.BooleanField(default=False)),
                ('last_reminder_sent', models.DateTimeField(blank=True, null=True)),
                ('paygo_transaction_id', models.CharField(blank=True, max_length=255)),
                ('set_cancelled', models.BooleanField(default=False)),
                ('late_cancel', models.BooleanField(default=False)),
                ('late_cancel_charge_transaction_id', models.CharField(blank=True, max_length=255)),
                ('missed', models.BooleanField(default=False)),
                ('outlook_event_id', models.TextField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TestResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('test_date', models.DateTimeField(blank=True, null=True)),
                ('test_type', models.CharField(max_length=255)),
                ('test_missed', models.BooleanField(default=False)),
                ('test_complete', models.DateTimeField(blank=True, null=True)),
                ('score', models.FloatField(blank=True, null=True)),
                ('reading', models.FloatField(blank=True, null=True)),
                ('reading_sub', models.FloatField(blank=True, null=True)),
                ('writing', models.FloatField(blank=True, null=True)),
                ('writing_sub', models.FloatField(blank=True, null=True)),
                ('math', models.FloatField(blank=True, null=True)),
                ('math_sub', models.FloatField(blank=True, null=True)),
                ('english', models.FloatField(blank=True, null=True)),
                ('science', models.FloatField(blank=True, null=True)),
                ('speaking', models.FloatField(blank=True, null=True)),
                ('listening', models.FloatField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutorAvailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('start', models.DateTimeField()),
                ('end', models.DateTimeField()),
            ],
            options={
                'ordering': ['start'],
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutoringPackage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('all_locations', models.BooleanField(default=False)),
                ('price', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('available', models.DateTimeField(blank=True, null=True)),
                ('expires', models.DateTimeField(blank=True, null=True)),
                ('individual_test_prep_hours', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('group_test_prep_hours', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('individual_curriculum_hours', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('active', models.BooleanField(default=True)),
                ('sku', models.CharField(blank=True, max_length=255)),
                ('product_id', models.CharField(blank=True, max_length=255)),
                ('magento_purchase_link', models.CharField(blank=True, max_length=255)),
                ('allow_self_enroll', models.BooleanField(default=True)),
                ('is_paygo_package', models.BooleanField(default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutoringPackagePurchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('price_paid', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('admin_note', models.TextField(blank=True)),
                ('purchase_reversed', models.DateTimeField(blank=True, null=True)),
                ('payment_required', models.BooleanField(default=False)),
                ('payment_link', models.CharField(blank=True, max_length=255)),
                ('payment_completed', models.DateTimeField(blank=True, null=True)),
                ('payment_confirmation', models.CharField(blank=True, max_length=255)),
                ('magento_payload', models.JSONField(blank=True, default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('sku', models.CharField(blank=True, max_length=255)),
                ('magento_status_code', models.SmallIntegerField(blank=True, null=True)),
                ('magento_response', models.TextField(blank=True)),
                ('paygo_transaction_id', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutoringService',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=255)),
                ('session_type', models.CharField(choices=[('t', 'Test Prep'), ('c', 'Curriculum')], max_length=1)),
                ('applies_to_group_sessions', models.BooleanField(default=False)),
                ('applies_to_individual_sessions', models.BooleanField(default=False)),
                ('level', models.CharField(blank=True, choices=[('a', 'AP'), ('h', 'Honors')], max_length=2)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutoringSessionNotes',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('notes', models.TextField(blank=True)),
                ('notes_file', models.FileField(blank=True, upload_to='tutoring_session_notes')),
                ('visible_to_student', models.BooleanField(default=True)),
                ('visible_to_parent', models.BooleanField(default=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutorTimeCard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('start', models.DateTimeField()),
                ('end', models.DateTimeField()),
                ('display_end', models.DateField(blank=True, null=True)),
                ('hourly_rate', models.DecimalField(decimal_places=2, max_digits=5)),
                ('total', models.DecimalField(decimal_places=2, default=0.0, max_digits=8)),
                ('admin_approval_time', models.DateTimeField(blank=True, null=True)),
                ('admin_note', models.TextField(blank=True)),
                ('tutor_approval_time', models.DateTimeField(blank=True, null=True)),
                ('tutor_note', models.TextField(blank=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TutorTimeCardLineItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('category', models.CharField(blank=True, max_length=255)),
                ('date', models.DateTimeField(blank=True, null=True)),
                ('hours', models.DecimalField(decimal_places=2, default=0.0, max_digits=5)),
                ('hourly_rate', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_time_card_line_items', to=settings.AUTH_USER_MODEL)),
                ('group_tutoring_session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='time_card_line_items', to='sntutoring.grouptutoringsession')),
                ('individual_tutoring_session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='time_card_line_items', to='sntutoring.studenttutoringsession')),
                ('time_card', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='line_items', to='sntutoring.tutortimecard')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
