# Generated by Django 4.2.5 on 2023-09-21 13:14

import cwtutoring.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cwtutoring', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('cwtasks', '0003_initial'),
        ('cwresources', '0001_initial'),
        ('cwusers', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tutortimecard',
            name='admin_approver',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='cwusers.administrator'),
        ),
        migrations.AddField(
            model_name='tutortimecard',
            name='tutor',
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='time_cards', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='tutoringsessionnotes',
            name='author',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tutoring_session_notes', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='tutoringsessionnotes',
            name='group_tutoring_session',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tutoring_session_notes', to='cwtutoring.grouptutoringsession'),
        ),
        migrations.AddField(
            model_name='tutoringsessionnotes',
            name='resources',
            field=models.ManyToManyField(related_name='tutoring_session_notes', to='cwresources.resource'),
        ),
        migrations.AddField(
            model_name='tutoringservice',
            name='locations',
            field=models.ManyToManyField(blank=True, related_name='tutoring_services', to='cwtutoring.location'),
        ),
        migrations.AddField(
            model_name='tutoringservice',
            name='tutors',
            field=models.ManyToManyField(blank=True, related_name='tutoring_services', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='tutoringpackagepurchase',
            name='purchase_reversed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reversed_tutoring_package_purchases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='tutoringpackagepurchase',
            name='purchased_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tutoring_package_purchases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='tutoringpackagepurchase',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tutoring_package_purchases', to='cwusers.student'),
        ),
        migrations.AddField(
            model_name='tutoringpackagepurchase',
            name='tutoring_package',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tutoring_package_purchases', to='cwtutoring.tutoringpackage'),
        ),
        migrations.AddField(
            model_name='tutoringpackage',
            name='group_tutoring_sessions',
            field=models.ManyToManyField(blank=True, related_name='tutoring_packages', to='cwtutoring.grouptutoringsession'),
        ),
        migrations.AddField(
            model_name='tutoringpackage',
            name='locations',
            field=models.ManyToManyField(blank=True, related_name='tutoring_packages', to='cwtutoring.location'),
        ),
        migrations.AddField(
            model_name='tutoringpackage',
            name='resource_groups',
            field=models.ManyToManyField(blank=True, related_name='tutoring_packages', to='cwresources.resourcegroup'),
        ),
        migrations.AddField(
            model_name='tutoringpackage',
            name='restricted_tutor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='restricted_tutoring_packages', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='tutoravailability',
            name='tutor',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availabilities', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='testresult',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='test_results', to='cwusers.student'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_student_tutoring_sessions', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='group_tutoring_session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_tutoring_sessions', to='cwtutoring.grouptutoringsession'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='individual_session_tutor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_tutoring_sessions', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='location',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_tutoring_sessions', to='cwtutoring.location'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='set_resources',
            field=models.ManyToManyField(related_name='student_tutoring_sessions', to='cwresources.resource'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='student',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tutoring_sessions', to='cwusers.student'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='tutoring_service',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_tutoring_sessions', to='cwtutoring.tutoringservice'),
        ),
        migrations.AddField(
            model_name='studenttutoringsession',
            name='tutoring_session_notes',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_tutoring_sessions', to='cwtutoring.tutoringsessionnotes'),
        ),
        migrations.AddField(
            model_name='recurringtutoravailability',
            name='tutor',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='recurring_availability', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='grouptutoringsession',
            name='diagnostic',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='group_tutoring_sessions', to='cwtutoring.diagnostic'),
        ),
        migrations.AddField(
            model_name='grouptutoringsession',
            name='location',
            field=models.ForeignKey(default=cwtutoring.models.get_default_location, on_delete=django.db.models.deletion.PROTECT, related_name='group_tutoring_sessions', to='cwtutoring.location'),
        ),
        migrations.AddField(
            model_name='grouptutoringsession',
            name='primary_tutor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='primary_group_tutoring_sessions', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='grouptutoringsession',
            name='resources',
            field=models.ManyToManyField(blank=True, related_name='group_tutoring_sessions', to='cwresources.resource'),
        ),
        migrations.AddField(
            model_name='grouptutoringsession',
            name='support_tutors',
            field=models.ManyToManyField(blank=True, related_name='support_group_tutoring_sessions', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='assigned_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='diagnostic',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='diagnostic_results', to='cwtutoring.diagnostic'),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='feedback_provided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='task_feedback', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='diagnostic_results', to='cwusers.student'),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_tasks', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='diagnosticresult',
            name='task',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='diagnostic_result', to='cwtasks.task'),
        ),
        migrations.AddField(
            model_name='diagnosticgrouptutoringsessionregistration',
            name='group_tutoring_sessions',
            field=models.ManyToManyField(related_name='diagnostic_gts_registrations', to='cwtutoring.grouptutoringsession'),
        ),
        migrations.AddField(
            model_name='diagnosticgrouptutoringsessionregistration',
            name='self_assigned_diagnostics',
            field=models.ManyToManyField(related_name='diagnostic_gts_registrations', to='cwtutoring.diagnostic'),
        ),
        migrations.AddField(
            model_name='diagnosticgrouptutoringsessionregistration',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='diagnostic_gts_registrations', to='cwusers.student'),
        ),
        migrations.AddField(
            model_name='diagnostic',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_diagnostics', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='diagnostic',
            name='resources',
            field=models.ManyToManyField(blank=True, related_name='diagnostics', to='cwresources.resource'),
        ),
        migrations.AddField(
            model_name='diagnostic',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='course',
            name='group_tutoring_sessions',
            field=models.ManyToManyField(blank=True, related_name='courses', to='cwtutoring.grouptutoringsession'),
        ),
        migrations.AddField(
            model_name='course',
            name='location',
            field=models.ForeignKey(default=cwtutoring.models.get_default_location, on_delete=django.db.models.deletion.PROTECT, related_name='courses', to='cwtutoring.location'),
        ),
        migrations.AddField(
            model_name='course',
            name='package',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='courses', to='cwtutoring.tutoringpackage'),
        ),
        migrations.AddField(
            model_name='course',
            name='primary_tutor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='courses', to='cwusers.tutor'),
        ),
        migrations.AddField(
            model_name='course',
            name='resources',
            field=models.ManyToManyField(blank=True, related_name='courses', to='cwresources.resource'),
        ),
        migrations.AddField(
            model_name='course',
            name='students',
            field=models.ManyToManyField(blank=True, related_name='courses', to='cwusers.student'),
        ),
    ]