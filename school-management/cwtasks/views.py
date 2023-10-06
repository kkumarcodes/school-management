import dateparser
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from django.http import HttpResponseBadRequest
from django.shortcuts import get_list_or_404, get_object_or_404
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.decorators import action
from cwnotifications.constants import notification_types
from cwnotifications.generator import create_notification

from cwusers.mixins import AccessStudentPermission
from cwusers.models import Student, Administrator, Counselor, Parent
from cwtasks.constants import COLLEGE_RESEARCH_FORM_KEY, TASK_TYPE_SCHOOL_RESEARCH
from cwtasks.utilities.task_manager import TaskManager
from cwuniversities.models import StudentUniversityDecision
from .serializers import (
    TaskSerializer,
    TaskTemplateSerializer,
    FormSerializer,
    FormListSerializer,
    FormSubmissionSerializer,
    FormSubmissionListSerializer,
    FormFieldSerializer,
    FormFieldEntrySerializer,
)
from .models import Task, TaskTemplate, Form, FormSubmission, FormField, FormFieldEntry


class TaskViewset(ModelViewSet, AccessStudentPermission):
    """ List, Create, Update Task
        DELETE action is supported, but it just updates the task to be archived
        Task can be completed/submitted by way of updating it
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = TaskSerializer

    def get_queryset(self):
        # Return all tasks. Permissions checks will kick in
        queryset = Task.objects.all()
        query_params = self.request.query_params

        # If user kwarg is presented, then we use that. Otherwise, we return tasks for current user
        if query_params.get("user"):
            queryset = Task.objects.filter(for_user__pk=query_params["user"]).filter(archived=None)

        # Counselor can get tasks for all of their students at once
        elif query_params.get("counselor"):
            queryset = Task.objects.filter(for_user__student__counselor=query_params["counselor"], archived=None)
        elif query_params.get("task_template"):
            queryset = queryset.filter(task_template__pk=query_params["task_template"])
        # If we're listing tasks, we return tasks for current user.
        elif self.request.method.lower() == "get" and not self.kwargs.get("pk"):
            if hasattr(self.request.user, "parent"):
                queryset = Task.objects.filter(
                    Q(for_user=self.request.user)
                    | Q(for_user__student__parent=self.request.user.parent, task_template__counseling_parent_task=True)
                ).distinct()
            else:
                queryset = Task.objects.filter(for_user=self.request.user).filter(archived=None)

        if query_params.get("start"):
            start = dateparser.parse(query_params["start"])
            if not start:
                raise ValueError(f"Invalid start: {query_params['start']}")
            queryset = queryset.filter(due__gte=start)
        if query_params.get("end"):
            end = dateparser.parse(query_params["end"])
            if not end:
                raise ValueError(f"Invalid end: {query_params['end']}")
            queryset = queryset.filter(due__lte=end)

        return (
            queryset.select_related("for_user__student", "task_template", "form", "diagnostic", "diagnostic_result")
            .prefetch_related("resources", "student_university_decisions", "file_uploads")
            .distinct()
        )

    def get_serializer_context(self):
        """ Add 'creator' to serializer context, so we can set Task.created_by when creating task """
        return {
            "creator": self.request.user if self.request else None,
            "admin": self.request.user if hasattr(self.request.user, "administrator") else None,
            "request": self.request,
        }

    def check_permissions(self, request):
        """ When listing tasks for specific user, ensure logged in user has access to user they are
            listing tasks for.
        """
        super(TaskViewset, self).check_permissions(request)
        if not hasattr(self.request.user, "administrator"):
            if request.query_params.get("counselor"):
                counselor = get_object_or_404(Counselor, pk=request.query_params["counselor"])
                if counselor.user != request.user:
                    self.permission_denied(request)

            if self.request.query_params.get("user"):
                allowed_user = request.user.pk == self.request.query_params.get("user")
                task_student = Student.objects.filter(user__pk=self.request.query_params.get("user")).first()
                if task_student and self.has_access_to_student(task_student):
                    allowed_user = True
                if not allowed_user:
                    self.permission_denied(request)

            if self.action == "create__bulk_create":
                students = Student.objects.filter(user__pk__in=request.data["for_user_bulk_create"])
                for student in students:
                    if not self.has_access_to_student(student):
                        self.permission_denied(request)

            if self.action == "create":
                student = Student.objects.filter(user=request.data.get("for_user")).first()
                if student and request.data.get("for_user") and not self.has_access_to_student(student):
                    self.permission_denied(request)
                elif not student:
                    self.permission_denied(request, message="Can only create tasks for students")

    def check_object_permissions(self, request, obj):
        """ This only runs for update/delete. We ensure task is for user or - if task is for student -
            user has access to student task is for.
        """
        # User is trying to alter their own task OR user is administrator so they can alter any task
        if obj.for_user == request.user or Administrator.objects.filter(user=request.user).exists():
            return True

        # Otherwise, confirm task is for student and user has access to that student
        task_student = Student.objects.filter(user=obj.for_user).first()
        if not (task_student and self.has_access_to_student(task_student)):
            self.permission_denied(request)

    def perform_update(self, serializer):
        """ Check to see if task is being completed, in which case we fire off a noti
        """
        instance: Task = self.get_object()
        original_sud = list(instance.student_university_decisions.values_list("pk", flat=True))
        originally_completed = instance.completed
        new_instance: Task = serializer.save()
        new_instance.refresh_from_db()
        if hasattr(instance.for_user, "student"):
            if new_instance.completed and not originally_completed:
                task_manager = TaskManager(new_instance)
                task_manager.complete_task(
                    actor=self.request.user, send_notification=instance.created_by != instance.for_user,
                )
            if (
                len(new_instance.for_user.student.counseling_student_types_list) > 0
                and new_instance.file_uploads.exists()
            ):
                new_instance.file_uploads.all().update(counseling_student=new_instance.for_user.student)

            new_suds = new_instance.student_university_decisions.exclude(pk__in=original_sud)
            if (new_instance.due or new_instance.visible_to_counseling_student) and new_suds.exists():
                task_manager = TaskManager(new_instance)
                task_manager.create_update_task_sud(new_suds)

        # For CAP tasks, we need to mark the task as assigned to student when it becomes
        # visible to studen
        if (
            new_instance.is_cap
            and new_instance.visible_to_counseling_student
            and not instance.visible_to_counseling_student
        ):
            new_instance.assigned_time = timezone.now()
            new_instance.save()

        return new_instance

    @action(methods=["post"], detail=False, url_name="bulk-create", url_path="bulk-create")
    def create__bulk_create(self, request, *args, **kwargs):
        """ Custom view action to create multiple tasks at once. Leverages self.perform_create for each create
            Just like create except:
            Data:
                for_user_bulk_create: List of users to create the task for
                <All other properties match regular ole' create/POST calls>
            Returns:
                List of all created tasks
        """
        users = get_list_or_404(User, pk__in=request.data.get("for_user_bulk_create"),)
        serializers = []
        for user in users:
            data = request.data.copy()
            data.update({"for_user": user.pk})
            serializer: TaskSerializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializers.append(serializer)

        tasks = [self.perform_create(serializer) for serializer in serializers]
        return Response(TaskSerializer(tasks, many=True).data, status=status.HTTP_201_CREATED)

    @action(methods=["post"], detail=True, url_name="remind", url_path="remind")
    def create__remind(self, request, *args, **kwargs):
        """ Special action that can be used to send an individual reminder for task as long as the task
            is not yet complete and is visible to student/parent if it is a cap task
            Returns: UPdated task
        """
        task: Task = self.get_object()
        if task.completed:
            raise ValidationError(detail="Cannot send reminder for completed task")
        if task.archived:
            raise ValidationError(detail="Cannot send reminder for archived task")
        if task.is_cap and not task.visible_to_counseling_student:
            raise ValidationError(detail="Cannot send reminder for CAP task that is not visible to student/parent")

        # Validation succeeds. Let's create our notification and return the updated task
        create_notification(
            task.for_user,
            notification_type=notification_types.INDIVIDUAL_TASK_REMINDER,
            related_object_pk=task.pk,
            related_object_content_type=ContentType.objects.get_for_model(Task),
        )
        task.last_reminder_sent = timezone.now()
        task.save()
        return Response(TaskSerializer(task).data)

    def perform_create(self, serializer) -> Task:
        """ Send notification """
        instance: Task = serializer.save()
        task_manager = TaskManager(instance)
        if instance.student_university_decisions.exists() and (instance.due or instance.visible_to_counseling_student):
            task_manager.create_update_task_sud()
        # Create notification for CAS tasks plus CAP tasks that are visible to student
        if (not instance.is_cap) or instance.visible_to_counseling_student:
            instance.assigned_time = timezone.now()
            instance.save()
            task_manager.send_task_created_notification(actor=self.request.user)
            if self.request.data.get("self_assigned"):
                task_manager.send_self_assigned_admin_notification()
        return instance

    # pylint: disable=unused-argument
    def destroy(self, request, *args, **kwargs):
        """ Destroying a task = setting it to archived.
            If task is a counseling task that does not repeat, then we just clear its due date (put it back in student's
            task "bank")
        """
        instance: Task = self.get_object()
        instance.visible_to_counseling_student = False
        if instance.task_template and not instance.task_template.repeatable:
            instance.due = None
        else:
            instance.archived = timezone.now()
        instance.save()
        return Response(self.serializer_class(instance, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["PUT"])
    def reassign(self, request, *args, **kwargs):
        """ Admins ONLY can reassign a task from one user to another.
            Task must be incomplete and not archived.
            New assignee will get a notification
            Arguments:
                This is a detail route so PK of Task must be included in URL
                In data: {'for_user'} Must be provided and reference new asignee user PK
        """
        super(TaskViewset, self).check_permissions(request)
        if not hasattr(self.request.user, "administrator"):
            self.permission_denied(request)

        task = self.get_object()
        if task.completed or task.archived:
            return HttpResponseBadRequest("Cannot reassign complete or archived tasks")
        user = get_object_or_404(User, pk=request.data.get("for_user"))
        task.for_user = user
        task.save()
        mgr = TaskManager(task)
        mgr.send_task_created_notification(actor=request.user)
        return Response(self.serializer_class(task, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["POST"], url_path="create-research-task", url_name="create_research_task")
    def create_college_research_task(self, request, *args, **kwargs):
        """ This is a very special view. It gets or creates a college research task for a student
            univerity decision
            Arguments (POST):
                student_university_decision: PK
        """
        sud = get_object_or_404(StudentUniversityDecision, pk=request.data.get("student_university_decision"))
        if not self.has_access_to_student(sud.student):
            self.permission_denied(request)
        # Look for a task for sud's student's user
        task = Task.objects.filter(
            form__key=COLLEGE_RESEARCH_FORM_KEY, for_user=sud.student.user, student_university_decisions=sud
        ).first()
        created = False
        if not task:
            #  Create our task
            created = True
            task = Task.objects.create(
                for_user=sud.student.user,
                form=Form.objects.get(key=COLLEGE_RESEARCH_FORM_KEY),
                created_by=request.user,
                allow_content_submission=False,
                allow_file_submission=False,
                task_type=TASK_TYPE_SCHOOL_RESEARCH,
                title=f"{sud.university.name} research",
            )
            task.student_university_decisions.add(sud)

        return Response(
            TaskSerializer(task, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TaskTemplateViewset(ModelViewSet):
    """ Create, Update TaskTemplate is restricted to Admins. List is available to Admins and Counselors
        DELETE action does not destroy instance, instead task template is "archived"
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = TaskTemplateSerializer

    def get_queryset(self):
        
        if hasattr(self.request.user, "administrator"):
            return TaskTemplate.objects.filter(archived=None).select_related("created_by")
        elif query_params.get("counselor"):
            queryset = Task.objects.filter(for_user__student__counselor=query_params["counselor"], archived=None)

        return (
            TaskTemplate.objects.filter(Q(created_by=None) | Q(created_by=self.request.user))
            .filter(archived=None)
            .select_related("created_by")
            .distinct()
        )

    def filter_queryset(self, queryset):
        """ Supported query params:
                - student Returns only TaskTemplates with tasks assigned to student
        """
        if self.request.query_params.get("student"):
            student = get_object_or_404(Student, pk=self.request.query_params["student"])
            queryset = queryset.filter(tasks__for_user__student=student).distinct()
            no_roadmap_key = queryset.filter(roadmap_key="")
            roadmap_templates = queryset.order_by("roadmap_key", "created_by").distinct("roadmap_key")
            return no_roadmap_key.union(roadmap_templates)
        return queryset

    def check_permissions(self, request):
        """ Only counselors and admins have access to this view """
        super(TaskTemplateViewset, self).check_permissions(request)
        user = self.request.user
        if not (hasattr(user, "administrator") or hasattr(user, "counselor")):
            self.permission_denied(self.request)

    def check_object_permissions(self, request, obj):
        super(TaskTemplateViewset, self).check_object_permissions(request, obj)
        # Counselor must be creator or retrieving
        if (
            not hasattr(self.request.user, "administrator")
            and request.method.lower() != "get"
            and obj.created_by != request.user
        ):
            self.permission_denied(request)

    # pylint: disable=unused-argument
    def destroy(self, request, *args, **kwargs):
        """ Destroying a task template => setting it to archived. Task Template is NOT actually deleted since metadata
        on related tasks is still useful :) """
        instance = self.get_object()
        instance.archived = timezone.now()
        instance.save()

        if instance.created_by and hasattr(instance.created_by, "counselor") and instance.roadmap_key:
            # We need to revert tasks for the counselor's students to use the roadmap version of the task template
            new_task_template = TaskManager.get_task_template_for_counselor(
                instance.created_by.counselor, instance.roadmap_key
            )
            TaskManager.apply_counselor_task_template_override(
                new_task_template, counselor=instance.created_by.counselor
            )

        return Response(self.serializer_class(instance).data)

    def perform_create(self, serializer):
        task_template: TaskTemplate = serializer.save()
        if not hasattr(self.request.user, "administrator"):
            task_template.created_by = self.request.user
            task_template.save()

        if (
            self.request.data.get("update_tasks")
            and task_template.created_by
            and hasattr(task_template.created_by, "counselor")
        ):
            # Update UNSUBMITTED tasks for counselor's student so they use updated task template
            TaskManager.apply_counselor_task_template_override(task_template)

        return task_template

    def perform_update(self, serializer):
        """ In addition to fields on serializer, this action supports:
            - update_tasks (bool; default False) whether or not tasks associated with task template should also be updated
        """
        old_object: TaskTemplate = self.get_object()
        old_resources = set(old_object.resources.values_list("pk", flat=True))
        old_pre_agenda_item_templates = set(old_object.pre_agenda_item_templates.values_list("pk", flat=True))
        new_object: TaskTemplate = serializer.save()

        # We update resources if they change
        update_resources = old_resources != set(new_object.resources.values_list("pk", flat=True))
        # We update pre_agenda_item_templates if they change
        update_pre_agenda_item_templates = old_pre_agenda_item_templates != set(new_object.pre_agenda_item_templates.values_list("pk", flat=True))
        if self.request.data.get("update_tasks"):
            if (
                self.request.data.get("update_tasks")
                and new_object.created_by
                and hasattr(new_object.created_by, "counselor")
            ):
                # Update UNSUBMITTED tasks for counselor's student so they use updated task template
                TaskManager.apply_counselor_task_template_override(new_object)
            TaskManager.update_tasks_for_template(new_object, update_resources, update_pre_agenda_item_templates)
        return new_object


class FormViewset(ModelViewSet):
    serializer_class = FormSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Form.objects.all()

    def get_serializer_class(self):
        if self.action == "list":
            return FormListSerializer
        return super(FormViewset, self).get_serializer_class()

    def check_permissions(self, request):
        super(FormViewset, self).check_permissions(request)
        # Only admins can create/update/delete forms
        if request.method not in SAFE_METHODS and not hasattr(self.request.user, "administrator"):
            self.permission_denied(request, message="Only admins can access non-safe methods")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class FormSubmissionViewset(ModelViewSet, AccessStudentPermission):
    serializer_class = FormSubmissionSerializer
    permission_classes = (IsAuthenticated,)
    queryset = FormSubmission.objects.all()

    def get_serializer_class(self):
        if self.action == "list":
            return FormSubmissionListSerializer
        return super(FormSubmissionViewset, self).get_serializer_class()

    def get_queryset(self):
        # Admins have access to all form submissions (including archived submissions)
        if hasattr(self.request.user, "administrator"):
            return FormSubmission.objects.all()
        # Counselor should only be able to access their students' form submissions (including archived submissions)
        counselor = Counselor.objects.filter(user=self.request.user).first()
        if counselor:
            return FormSubmission.objects.filter(
                Q(task__for_user__student__counselor=counselor)
                | Q(task__for_user__parent__in=[student.parent for student in counselor.students.all()])
            ).distinct()
        # Student should only have access to their own form submissions
        student = Student.objects.filter(user=self.request.user).first()
        if student:
            return FormSubmission.objects.filter(archived=None).filter(task__for_user=student.user)
        # Parent should only have access to their own form submissions and their student-child form submissions
        parent = Parent.objects.filter(user=self.request.user).first()
        if parent:
            return FormSubmission.objects.filter(archived=None).filter(
                Q(task__for_user=parent.user) | Q(task__for_user__student__parent=parent)
            )
        return FormSubmission.objects.none()

    def filter_queryset(self, queryset):
        """ Retrieve form_submission by task.pk """
        if self.request.query_params.get("task"):
            return queryset.filter(task=self.request.query_params["task"])
        return super(FormSubmissionViewset, self).filter_queryset(queryset)

    def check_permissions(self, request):
        super(FormSubmissionViewset, self).check_permissions(request)
        if request.method == "POST":
            for_user = Task.objects.get(pk=request.data["task"]).for_user
            student = Student.objects.filter(user=for_user).first()
            parent = Parent.objects.filter(user=for_user).first()
            if student and not self.has_access_to_student(student):
                self.permission_denied(request)
            if (
                parent
                and not request.user == for_user
                and not hasattr(request.user, "administrator")
                and not User.objects.filter(profile__counselor__students__parent=parent).exists()
            ):
                self.permission_denied(request)

    def check_object_permissions(self, request, obj):
        """ Ensure current user has permission to submit task form """
        super(FormSubmissionViewset, self).check_object_permissions(request, obj)
        student = Student.objects.filter(user=obj.task.for_user).first()
        parent = Parent.objects.filter(user=obj.task.for_user).first()
        if hasattr(request.user, "administrator"):
            return True
        if hasattr(request.user, "counselor"):
            if student and not self.has_access_to_student(student, request=request):
                self.permission_denied(request)
            if parent and not request.user in [student.counselor.user for student in parent.students.all()]:
                self.permission_denied(request)
        if hasattr(request.user, "parent"):
            if student and not self.has_access_to_student(student, request=request):
                self.permission_denied(request)
            if parent and not request.user == parent.user:
                self.permission_denied(request)
        if hasattr(request.user, "student") and not obj.task.for_user == request.user:
            self.permission_denied(request)

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    # pylint: disable=unused-argument
    def destroy(self, request, *args, **kwargs):
        """ Destroying a form submission => setting it to archived."""
        instance = self.get_object()
        instance.archived = timezone.now()
        instance.save()
        return Response(self.serializer_class(instance, context=self.get_serializer_context()).data)

    @action(methods=["GET"], detail=False, url_path="college-research", url_name="college_research")
    def get_college_research(self, request, *args, **kwargs):
        """ Retrieve all college research form submissions for student (with nested form_field_entries)
        Query Params:
            ?student {PK} Student to get college_research form submissions for
        """
        if not request.query_params.get("student"):
            return HttpResponseBadRequest("Must provide student query param")
        student = get_object_or_404(Student, pk=request.query_params.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(request)
        form_submissions = FormSubmission.objects.filter(form__key=COLLEGE_RESEARCH_FORM_KEY).filter(
            task__for_user__student=student
        )
        return Response(FormSubmissionSerializer(form_submissions, many=True).data)


class FormFieldViewset(ModelViewSet):
    serializer_class = FormFieldSerializer
    permission_classes = (IsAuthenticated,)
    queryset = FormField.objects.all()

    def get_queryset(self):
        """
        Admin only have access to standard fields (editable=False)
        Counselors have access to admin created fields (editable=False) and their own fields
        """
        if hasattr(self.request.user, "administrator"):
            return FormField.objects.filter(editable=False, hidden=False)
        if hasattr(self.request.user, "counselor"):
            return FormField.objects.filter(hidden=False).filter(Q(editable=False) | Q(created_by=self.request.user))
        student = Student.objects.filter(user=self.request.user).first()
        if student:
            return FormField.objects.filter(hidden=False).filter(
                Q(editable=False) | Q(created_by=student.counselor.user)
            )
        parent = Parent.objects.filter(user=self.request.user).first()
        if parent:
            counselor_users = [student.counselor.user for student in parent.students.all()]
            return (
                FormField.objects.filter(hidden=False)
                .filter(Q(editable=False) | Q(created_by__in=counselor_users))
                .distinct()
            )
        return FormField.objects.none()

    def check_permissions(self, request):
        if (
            request.method not in SAFE_METHODS
            and not hasattr(self.request.user, "administrator")
            and not hasattr(self.request.user, "counselor")
        ):
            self.permission_denied(request, message="Only admins and counselors can access non-safe methods")

    def check_object_permissions(self, request, obj):
        """ Ensure current user has access to form field """
        super(FormFieldViewset, self).check_object_permissions(request, obj)
        if hasattr(self.request.user, "administrator") and not obj.editable:
            return True
        if hasattr(self.request.user, "counselor") and obj.created_by == request.user:
            return True
        self.permission_denied(request)

    def perform_create(self, serializer):
        if hasattr(self.request.user, "administrator"):
            return serializer.save(editable=False, created_by=self.request.user)
        if hasattr(self.request.user, "counselor"):
            return serializer.save(editable=True, created_by=self.request.user)

    def perform_update(self, serializer):
        if hasattr(self.request.user, "administrator") or hasattr(self.request.user, "counselor"):
            return serializer.save(updated_by=self.request.user)

    # pylint: disable=unused-argument
    def destroy(self, request, *args, **kwargs):
        """ Destroy request sets form field property hidden=True. Form field is NOT actually deleted :) """
        instance = self.get_object()
        instance.hidden = True
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FormFieldEntryViewset(ModelViewSet, AccessStudentPermission):
    serializer_class = FormFieldEntrySerializer
    permission_classes = (IsAuthenticated,)
    queryset = FormFieldEntry.objects.all()

    def get_queryset(self):
        user = self.request.user
        # Admin has access to all visible form
        admin = Administrator.objects.filter(user=user).first()
        if admin:
            return FormFieldEntry.objects.all()
        # Counselor should be able to access their students' and their students' parent form field entries
        counselor = Counselor.objects.filter(user=user).first()
        if counselor:
            return FormFieldEntry.objects.filter(
                Q(form_submission__task__for_user__student__counselor=counselor)
                | Q(form_submission__task__for_user__parent__students__counselor=counselor)
            )
        # Parent should  have access to their own form field entries and that of their student-child
        parent = Parent.objects.filter(user=user).first()
        if parent:
            return FormFieldEntry.objects.filter(
                Q(form_submission__task__for_user=parent.user)
                | Q(form_submission__task__for_user__student__parent=parent)
            )
        # Student should have access to their own form field entries
        student = Student.objects.filter(user=user).first()
        if student:
            return FormFieldEntry.objects.filter(form_submission__task__for_user=student.user)
        return FormFieldEntry.objects.none()

    def check_object_permissions(self, request, obj):
        """ Ensure current user has access to Form Field Entry """
        super(FormFieldEntryViewset, self).check_object_permissions(request, obj)
        student = Student.objects.filter(user=obj.form_submission.task.for_user).first()
        parent = Parent.objects.filter(user=obj.form_submission.task.for_user).first()
        if student and not self.has_access_to_student(student):
            self.permission_denied(request)
        if (
            parent
            and not request.user == parent.user
            and not hasattr(request.user, "administrator")
            and not request.user in [student.counselor.user for student in parent.students.all()]
        ):
            self.permission_denied(request)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        """ Update associated form submission whenever a form field entry is updated """
        instance = self.get_object()
        instance.form_submission.updated_by = self.request.user
        instance.form_submission.save()
        serializer.save(updated_by=self.request.user)

    # pylint: disable=unused-argument
    def destroy(self, request, *args, **kwargs):
        """ Cant destroy form field entries """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
