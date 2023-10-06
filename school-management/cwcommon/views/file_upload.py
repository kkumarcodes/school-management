import json
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy
from django.views import View
from django.shortcuts import get_object_or_404
from django.core.files.base import ContentFile
from django.contrib.contenttypes.models import ContentType
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response
from rest_framework import status

from cwcommon.utilities.google_drive import GoogleDriveManager, GoogleDriveException
from cwcommon.models import FileUpload
from cwcommon.serializers.file_upload import FileUploadSerializer
from cwusers.models import get_cw_user, Student
from cwusers.mixins import AccessStudentPermission
from cwnotifications.generator import create_notification
from cwtasks.models import Task


class FileUploadView(View, AccessStudentPermission):
    """ View for creating and downloading FileUpload objects
        TODO: Refactor to use check_object_permissions
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(FileUploadView, self).dispatch(request, *args, **kwargs)

    def get(self, request, slug):
        """ Download a file upload """
        file_upload: FileUpload = get_object_or_404(FileUpload, slug=slug)
        if not file_upload.bulletin and not request.user.is_authenticated:
            return HttpResponseRedirect("%s?redirect=%s" % (reverse_lazy("cw_login"), request.build_absolute_uri()))

        authorized = False
        if file_upload.created_by == request.user or hasattr(request.user, "administrator"):
            authorized = True

        # TODO: As FileUploads get related to more other objects, we should break out this case authentication
        # into utility so view doesn't get too big
        # Announcement file uploads are publicly availably
        if file_upload.bulletin:
            authorized = True
        elif file_upload.task:
            if file_upload.task.for_user == request.user or file_upload.task.created_by == request.user:
                authorized = True
            elif (
                hasattr(request.user, "tutor") or hasattr(request.user, "counselor") or hasattr(request.user, "parent")
            ):
                cw_user = get_cw_user(request.user)
                # Upload is for task for one of current user's students
                if cw_user.students.filter(user__tasks=file_upload.task).exists():
                    authorized = True
        elif file_upload.diagnostic_result:
            if hasattr(request.user, "tutor") and request.user.tutor.is_diagnostic_evaluator:
                authorized = True
            elif self.has_access_to_student(file_upload.diagnostic_result.student):
                authorized = True
        elif file_upload.test_result:
            if self.has_access_to_student(file_upload.test_result.student):
                authorized = True
        elif file_upload.counseling_student:
            if self.has_access_to_student(file_upload.counseling_student):
                authorized = True
        elif hasattr(file_upload.created_by, "student"):
            if self.has_access_to_student(file_upload.created_by.student):
                authorized = True
        elif file_upload.bulletin:
            if file_upload.bulletin.visible_to_notification_recipients.filter(user=request.user).exists():
                authorized = True

        elif file_upload.counselor_meeting and self.has_access_to_student(file_upload.counselor_meeting.student):
            authorized = True
        elif file_upload.tutoring_session_notes:
            students = Student.objects.filter(
                Q(tutoring_session__tutoring_session_notes=file_upload.tutoring_session_notes)
                | Q(
                    tutoring_sessions__group_tutoring_session__tutoring_session_notes=file_upload.tutoring_session_notes
                )
            ).distinct()
            if any([self.has_access_to_student(x) for x in students]):
                authorized = True

        if (
            not authorized
            and hasattr(file_upload, "diagnostic_result_recommendation")
            and self.has_access_to_student(file_upload.diagnostic_result_recommendation.student)
        ):
            authorized = True

        if not authorized:
            return HttpResponseForbidden()

        # Finally! We get to return.
        # Let's check if file_upload is a link:
        if file_upload.link:
            return HttpResponseRedirect(file_upload.link)
        # No? Then must be a file_resource
        return HttpResponseRedirect(file_upload.file_resource.url)

    def post(self, request):
        """ Create a new FileUpload
            Arguments:
                FILES['file'] or 'link' (exclusive)
                Note: 'link' is an object with `name` and `url` fields
                POST['tags'] JSON Serialized list of strings that become FileUpload.tags
            Returns:
                slug of created FileUpload
        """
        if not request.user.is_authenticated:
            return HttpResponseForbidden("")

        link = None
        if not request.FILES.get("file"):
            link = json.loads(request.body)["link"]

        if request.FILES.get("file") and link:
            return HttpResponseBadRequest("Cannot upload File and Link.")

        if not request.FILES.get("file") and not link:
            return HttpResponseBadRequest("Upload must include File or Link")

        # We have a file, save our model
        if request.FILES.get("file"):
            temp_file = FileUpload.objects.create(title=request.FILES["file"].name, created_by=request.user)
            temp_file.file_resource.save(request.FILES["file"].name, ContentFile(request.FILES["file"].read()))

        # We have a link, save our model
        if link:
            temp_file = FileUpload.objects.create(title=link["name"], link=link["url"], created_by=request.user)

        if request.POST.get("tags"):
            try:
                temp_file.tags = json.loads(request.POST["tags"])
                temp_file.save()
            except json.JSONDecodeError:
                return HttpResponseBadRequest(
                    "File was created, but tags are invalid. Please ensure tags is a JSON serialized list of strings."
                )
        return JsonResponse(FileUploadSerializer(temp_file).data)


class FileUploadFromGoogleDriveView(APIView, AccessStudentPermission):
    """ View to create FileUpload from a Google Doc
        ONLY SUPPORTS DOCS and not other files from Google Drive
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        """ Arguments (POST data):
                access_token: OAuth access token for user that Google Drive file belongs to
                file_id: ID of Google Doc to download as Word file and
                filename: Name of Google Doc (becomes name of FileUpload)
                tags: Optional array of strings that become FileUpload.tags
                counseling_student: Optional PK of student who gets set as FileUpload.counseling_student
                task: Optional PK of task that becomes FileUpload.task
        """
        if not request.user.is_authenticated:
            self.permission_denied(request)
        counseling_student = task = None
        if not all([request.data.get(x) for x in ("access_token", "file_id", "filename")]):
            return Response(
                {"detail": "access_token, file_id and filename are required "}, status=status.HTTP_400_BAD_REQUEST
            )
        if request.data.get("counseling_student"):
            counseling_student = get_object_or_404(Student, pk=request.data["counseling_student"])
            if not self.has_access_to_student(counseling_student):
                self.permission_denied(request)
        if request.data.get("task"):
            task = get_object_or_404(Task, pk=request.data["task"])
        try:
            mgr = GoogleDriveManager()
            file_upload: FileUpload = mgr.export_google_doc(
                request.data["file_id"], request.data["access_token"], request.data["filename"]
            )
        except GoogleDriveException:
            return Response({"detail": "Google Drive error"}, status=status.HTTP_400_BAD_REQUEST)
        if request.data.get("tags"):
            file_upload.tags = request.data["tags"]
        if counseling_student:
            file_upload.counseling_student = counseling_student
        if task:
            file_upload.task = task
        file_upload.save()
        return Response(FileUploadSerializer(file_upload).data, status=status.HTTP_201_CREATED)


class FileUploadListUpdateViewset(AccessStudentPermission, ModelViewSet):
    """ File Uploads can be updated (name and tags only)
        Although they are most often retrieved as related objects on other models, FileUploads can also be LISTed
        unto themselves. This is useful in the following scenarios:
            - Listing Counselor File Uploads for a student
            - Listing Tutor file uploads for a student (not yet implemented)
            - Listing Admin file uploads for a student (not yet implemented)

        NOTE THAT DETAIL ROUTE USES slug AS LOOKUP FIELD INSTEAD OF pk
    """

    serializer_class = FileUploadSerializer
    permission_classes = (IsAuthenticated,)
    queryset = FileUpload.objects.all()
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    # To LIST, one of the following query params MUST be provided
    required_query_params = ("counseling_student",)

    def check_permissions(self, request):
        """ Super strict permissions. Check each query param """
        if request.query_params.get("counseling_student"):
            student = get_object_or_404(Student, pk=request.query_params["counseling_student"])
            if not self.has_access_to_student(student):
                self.permission_denied(request)

    def check_object_permissions(self, request, obj: FileUpload):
        """ Must be admin or object creator """
        super().check_object_permissions(request, obj)
        if obj.created_by == request.user or hasattr(request.user, "administrator"):
            return True
        # Counselors can edit files for their students
        if obj.counseling_student and obj.counseling_student.counselor.user == request.user:
            return True
        if hasattr(obj.created_by, "student") and obj.created_by.student.counselor.user == request.user:
            return True
        self.permission_denied(request)

    def filter_queryset(self, queryset):
        """ Here's where things get fun. You can provide the following query params (they match model fields)
            ?counseling_student=<Student.pk>
            ?tags=<string>
            ?counselor_meeting=<CounselorMeeting.pk>
            ?tutoring_session_notes=<TutoringSessionNotes.pk>
        """
        # If we're updating, then we just return queryset
        if self.request.method.lower() in ["delete", "patch"]:
            return queryset

        if not any([x in self.request.query_params for x in self.required_query_params]):
            raise ValidationError(f"Query params required. Chose from: {self.required_query_params}")

        counseling_student = self.request.query_params.get("counseling_student", None)

        # Otherwise query params MUST be provided
        query_params = dict(
            [
                (x, self.request.query_params[x])
                for x in self.required_query_params
                if (x in self.request.query_params and x != "counseling_student")
            ]
        )
        if self.request.query_params.get("tags"):
            query_params["tags__icontains"] = self.request.query_params["tags"]

        queryset = queryset.filter(**query_params)
        if counseling_student:
            obj = get_object_or_404(Student, pk=counseling_student)
            # We consider a file for a counseling student if it was created by that student (and isn't a CAS file)
            # OR if it is related to student through FileUpload.counseling_student
            queryset = queryset.filter(
                Q(counseling_student=obj) | Q(Q(created_by__student=obj) & Q(test_result=None, diagnostic_result=None))
            )
        return queryset

    def perform_update(self, serializer):
        """ If we are adding a counseling_student file and current user is not counselor, notify counselor """
        file_upload: FileUpload = serializer.save()
        if (
            file_upload.counseling_student
            and file_upload.counseling_student.counselor
            and not (self.request.user == file_upload.counseling_student.counselor.user)
        ):
            create_notification(
                file_upload.counseling_student.counselor.user,
                notification_type="counselor_file_upload",
                related_object_content_type=ContentType.objects.get_for_model(FileUpload),
                related_object_pk=file_upload.pk,
            )

    def create(self):
        raise MethodNotAllowed("post")

    def perform_destroy(self, obj):
        obj = self.get_object()
        obj.active = False
        obj.save()
        return obj

    def retrieve(self):
        raise MethodNotAllowed("retrieve")
