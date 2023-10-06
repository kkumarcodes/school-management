# Generated by Django 4.2.5 on 2023-09-21 13:14

import cwcommon.models
from decimal import Decimal
import django.contrib.postgres.fields
import django.core.serializers.json
import django.core.validators
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AgendaItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('order', models.IntegerField(default=1)),
                ('counselor_title', models.CharField(blank=True, max_length=255)),
                ('student_title', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='AgendaItemTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('key', models.TextField(blank=True)),
                ('order', models.IntegerField(default=1)),
                ('active', models.BooleanField(default=True)),
                ('counselor_title', models.CharField(blank=True, max_length=255)),
                ('student_title', models.CharField(blank=True, max_length=255)),
                ('counselor_instructions', models.TextField(blank=True)),
                ('repeatable', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='CounselingHoursGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('number_of_hours', models.DecimalField(decimal_places=2, help_text='Number of hours granted to student. Must be positive.', max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('marked_paid', models.BooleanField(default=False, help_text='If hours were paid for via Magento OR marked paid for by admin')),
                ('amount_paid', models.DecimalField(blank=True, decimal_places=2, default=0.0, help_text='The amount that was paid for the hours', max_digits=8, null=True)),
                ('note', models.TextField(blank=True, help_text='Optional note on what these hours are for. Can be set by admin if they are granting hours')),
                ('magento_id', models.TextField(blank=True, help_text='ID of Magento Order from which these hours were created (if applicable)')),
                ('include_in_hours_bank', models.BooleanField(default=True, help_text='Whether or not we should include this hours grant when summing up how many hours the student has total/remaining')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselingPackage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('counseling_student_type', models.CharField(blank=True, help_text='All students of this type will automatically get this package applied', max_length=255)),
                ('number_of_hours', models.DecimalField(decimal_places=2, help_text='Number of hours included in package', max_digits=6)),
                ('package_name', models.CharField(blank=True, help_text='Customer readable name of package', max_length=255)),
                ('grade', models.IntegerField(help_text='Grade in which student starts working with CW to get this package', null=True)),
                ('semester', models.IntegerField(help_text='Semester in which student starts working with CW to get this package. 1 = Fall. 2 = Spring/Summer', null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselorAvailability',
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
            name='CounselorEventType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('duration', models.IntegerField(null=True)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselorMeeting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('title', models.TextField(blank=True)),
                ('start', models.DateTimeField(blank=True, null=True)),
                ('end', models.DateTimeField(blank=True, null=True)),
                ('duration_minutes', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('private_notes', models.TextField(blank=True)),
                ('student_notes', models.TextField(blank=True)),
                ('last_reminder_sent', models.DateTimeField(blank=True, null=True)),
                ('cancelled', models.DateTimeField(blank=True, null=True)),
                ('student_schedulable', models.BooleanField(default=False)),
                ('notes_message_note', models.TextField(blank=True)),
                ('notes_message_subject', models.TextField(blank=True)),
                ('notes_message_last_sent', models.DateTimeField(blank=True, null=True)),
                ('link_schedule_meeting_pk', models.IntegerField(blank=True, null=True)),
                ('notes_finalized', models.BooleanField(default=False)),
                ('outlook_event_id', models.TextField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselorMeetingTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('key', models.TextField(blank=True)),
                ('order', models.SmallIntegerField(default=1)),
                ('title', models.TextField(blank=True)),
                ('counselor_instructions', models.TextField(blank=True)),
                ('student_instructions', models.TextField(blank=True)),
                ('description', models.TextField(blank=True)),
                ('grade', models.DecimalField(blank=True, decimal_places=1, max_digits=3, null=True)),
                ('semester', models.FloatField(blank=True, choices=[(1, 1), (1.5, 1.5), (2, 2), (2.5, 2.5), (3, 3), (3.5, 3.5)], null=True)),
                ('create_when_applying_roadmap', models.BooleanField(default=False)),
                ('use_agenda', models.BooleanField(default=True, help_text='Whether or not counselors can set an agenda for meetings that use this meeting type')),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='CounselorNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('category', models.CharField(choices=[('academics', 'Academics'), ('activities', 'Activities'), ('colleges', 'Colleges'), ('majors', 'Majors'), ('other', 'Other'), ('application_work', 'Application Work'), ('private', 'Private (Counselor)'), ('testing', 'Testing')], default='other', max_length=255)),
                ('note', models.TextField(blank=True)),
                ('note_date', models.DateField(blank=True, null=True)),
                ('note_title', models.TextField(blank=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselorTimeCard',
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
                ('counselor_approval_time', models.DateTimeField(blank=True, null=True)),
                ('counselor_note', models.TextField(blank=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CounselorTimeEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('date', models.DateTimeField(null=True)),
                ('hours', models.DecimalField(decimal_places=2, default=0.0, max_digits=5)),
                ('marked_paid', models.BooleanField(default=False)),
                ('amount_paid', models.DecimalField(blank=True, decimal_places=2, default=0.0, max_digits=8, null=True)),
                ('category', models.CharField(choices=[('meeting', 'Meeting'), ('ACT', 'ACT'), ('SAT', 'SAT'), ('college', 'College'), ('other', 'Other'), ('meeting_general', 'Meeting - General'), ('meeting_college_research', 'Meeting - College Research'), ('meeting_activity_review', 'Meeting - Action Review'), ('meeting_course_selection', 'Meeting - Course Selection'), ('meeting_essay_brainstorming', 'Meeting - Essay Brainstorming'), ('other_general', 'Other - General'), ('other_essay_review_and_editing', 'Other - Essay Review and Editing'), ('other_phone_call', 'Other - Phone Call'), ('other_follow_up_email_or_notes', 'Other - Follow Up Email or Notes'), ('other_college_research_prep', 'Other - College Research Prep'), ('other_activity_review_prep', 'Other - Activity Review Prep'), ('other_general_meeting_prep', 'Other - General Meeting Prep'), ('other_course_selection_prep', 'Other - Course Selection Prep'), ('admin_training', 'Admin - Training'), ('admin_freshmen_forum', 'Admin - Freshmen Forum'), ('admin_the_gut_check', 'Admin - The Gut Check'), ('admin_office_hours', 'Admin - Office Hours'), ('admin_counseling_call', 'Admin - Counseling Calls'), ('admin_meeting_with_manager', 'Admin - Meeting with Manager'), ('admin_miscellaneous_admin_tasks', 'Admin - Miscellaneous Admin Tasks')], default='meeting_general', max_length=255)),
                ('note', models.TextField(blank=True)),
                ('pay_rate', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('include_in_hours_bank', models.BooleanField(default=True, help_text='Whether or not we should include this time when summing up how many hours the student has total/remaining')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RecurringCounselorAvailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('active', models.BooleanField(default=True)),
                ('availability', models.JSONField(default=cwcommon.models.get_default_availability, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('locations', models.JSONField(default=cwcommon.models.get_default_locations, encoder=django.core.serializers.json.DjangoJSONEncoder)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Roadmap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True)),
                ('active', models.BooleanField(default=True)),
                ('category', models.CharField(blank=True, max_length=255)),
                ('repeatable', models.BooleanField(default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='StudentActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('category', models.CharField(choices=[('Summer Activity', 'Summer Activity'), ('Work Experience', 'Work Experience'), ('Award', 'Award'), ('Other', 'Other')], default='Other', max_length=255)),
                ('common_app_category', models.CharField(blank=True, max_length=255)),
                ('position', models.CharField(blank=True, max_length=255)),
                ('intend_to_participate_college', models.BooleanField(default=False)),
                ('during_school_year', models.BooleanField(default=False)),
                ('during_school_break', models.BooleanField(default=False)),
                ('all_year', models.BooleanField(default=False)),
                ('years_active', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), blank=True, default=list, size=None)),
                ('hours_per_week', models.DecimalField(decimal_places=1, default=0.0, max_digits=5)),
                ('weeks_per_year', models.DecimalField(decimal_places=1, default=0.0, max_digits=5)),
                ('awards', models.TextField(blank=True, null=True)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('order', models.PositiveIntegerField()),
                ('post_graduate', models.BooleanField(default=False)),
                ('recognition', models.CharField(blank=True, choices=[('School', 'School'), ('State/Regional', 'State/Regional'), ('National', 'National'), ('International', 'International')], max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
