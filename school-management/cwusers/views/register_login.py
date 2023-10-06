"""
    This module contains views to facilitate the process of registering for an account
    (including accepting an invitation) and logging in.
"""
import sentry_sdk
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, reverse, get_object_or_404
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseForbidden
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views import View
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from cwusers.models import Student, Counselor, Parent, Tutor, Administrator, get_cw_user
from cwusers.serializers.users import StudentSerializer, ParentSerializer
from cwusers.mixins import AccessStudentPermission
from cwusers.constants import user_types
from cwusers.utilities.managers import StudentManager
from cwnotifications.generator import create_notification
from cwtutoring.models import Course

AVAILABLE_DEMO_ACCOUNTS = ["student", "tutor", "admin", "counselor", "parent"]


class LoginView(APIView):
    """View used to authenticate and login a user
    """

    def post(self, request):
        """
            Arguments:
                username {String}
                password {String}
                demo_account {String. One of 'student', 'admin', 'tutor'}
                    ^^ Use this to login to a demo account ON STAGING OR DEV. Looks for user with username
                        matching demo_account
            Returns:
                Failure: 403 upon failure with user-readable message
                Success: JSON obj with { userID, userType, redirectURL }
                    Redirect user to redirectURL upon successful login (it will take them to their dashboard)
        """
        if request.data.get("demo_account"):
            user = User.objects.filter(username=request.data["demo_account"]).first()
            if not (user and user.username in AVAILABLE_DEMO_ACCOUNTS):
                return HttpResponseBadRequest("Invalid demo account")
            user = authenticate(request, username=user.username, password=user.username)
        else:
            # Case insensitive
            existing_user = User.objects.filter(username__iexact=request.data.get("username")).first()
            username = existing_user.username if existing_user else request.data.get("username")
            user = authenticate(request, username=username, password=request.data.get("password"),)
        if user is not None:
            for model_class in [Student, Counselor, Parent, Tutor, Administrator]:
                cwuser = model_class.objects.filter(user=user).first()
                if cwuser:
                    login(request, user)
                    return Response(
                        {
                            "userID": user.id,
                            "userType": cwuser.user_type,
                            "redirectURL": reverse("platform", kwargs={"platform_type": cwuser.user_type}),
                        }
                    )
            # User account exists, but no related cwuser model exists
            return Response({"detail": "Invalid user type"}, status=status.HTTP_403_FORBIDDEN)

        return Response({"detail": "Invalid username/password"}, status=status.HTTP_403_FORBIDDEN)

    def get(self, request):
        """Returns login form unless the user is already logged in, in which case we redirect to platform
        """
        if request.user.is_authenticated:
            for model_class in [Student, Counselor, Parent, Tutor, Administrator]:
                cwuser = model_class.objects.filter(user=request.user).first()
                if cwuser:
                    redirect_url = reverse("platform", kwargs={"platform_type": cwuser.user_type})
                    query_string = request.META["QUERY_STRING"]
                    if query_string:
                        redirect_url += f"?{query_string}"
                    return HttpResponseRedirect(redirect_url)
        return render(request, "cwusers/login.html")


class RegisterView(APIView):
    """View used to accept platform invitation, and submit registration
    """

    def get(self, request, uuid):
        user = User.objects.filter(
            Q(student__slug=uuid)
            | Q(parent__slug=uuid)
            | Q(tutor__slug=uuid)
            | Q(counselor__slug=uuid)
            | Q(administrator__slug=uuid)
        ).first()
        if not user:
            return HttpResponse("Invalid invite link")
        elif user and user.has_usable_password():
            return HttpResponseRedirect(reverse("cw_login"))

        return render(request, "cwusers/login.html", context={"register_uuid": uuid, "register_email": user.username},)

    def post(self, request):
        """Post registration attempt
            Arguments:
                uuid: UUID identifying CWUser model that is registering
                password
                timezone: String timezone to set as registration_timezone for user
            Returns:
                same as login
        """
        data = request.data
        if not ("uuid" in data and "password" in data):
            return HttpResponseBadRequest("Invalid Registration Details")
        uuid = data["uuid"]
        user = User.objects.filter(
            Q(student__slug=uuid)
            | Q(parent__slug=uuid)
            | Q(tutor__slug=uuid)
            | Q(counselor__slug=uuid)
            | Q(administrator__slug=uuid)
        ).first()
        if (not user) or user.has_usable_password():
            return HttpResponseBadRequest("Invalid Registration Details (User)")
        user.set_password(data["password"])
        user.save()
        # Create notification for admins
        admins = Administrator.objects.all()
        notification_data = {
            "related_object_content_type": ContentType.objects.get_for_model(User),
            "related_object_pk": user.pk,
            "notification_type": "user_accepted_invite",
        }
        [create_notification(a.user, **notification_data) for a in admins]

        new_user_notification_data = {
            "related_object_content_type": ContentType.objects.get_for_model(User),
            "related_object_pk": user.pk,
            "notification_type": "registration_success",
        }
        create_notification(user, **new_user_notification_data)

        login(request, user)
        cwuser = get_cw_user(user)
        cwuser.accepted_invite = timezone.now()
        cwuser.registration_timezone = data.get("timezone")
        cwuser.save()
        return JsonResponse(
            {
                "userID": user.id,
                "userType": cwuser.user_type,
                "redirectURL": reverse("platform", kwargs={"platform_type": cwuser.user_type}),
            }
        )


class RegisterCourseView(APIView):
    """ Registration view for peeps registering for a course from the course landing page.
        Note that registered students/parents get platform invite, and will recieve payment completion
        form via link from Magento
    """

    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        """ Arguments:
                Strings (all required:)
                    student_first_name, student_last_name, student_email
                    parent_first_name, parent_last_name, parent_email
                timezone: String timezone to set as registration_timezone for user
                course {pk}

            Returns:
                Status Complete
        """
        course = get_object_or_404(Course, pk=request.data.get("course"))
        parent_data = {
            "first_name": request.data.get("parent_first_name"),
            "last_name": request.data.get("parent_last_name"),
            "email": request.data.get("parent_email"),
        }
        existing_parent = Parent.objects.filter(invitation_email=parent_data["email"]).first()

        parent_serializer = ParentSerializer(data=parent_data, instance=existing_parent)
        student_data = {
            "first_name": request.data.get("student_first_name"),
            "last_name": request.data.get("student_last_name"),
            "email": request.data.get("student_email"),
        }
        existing_student = Student.objects.filter(invitation_email=student_data["email"]).first()

        student_serializer = StudentSerializer(data=student_data, instance=existing_student)
        parent_valid = parent_serializer.is_valid()
        student_valid = student_serializer.is_valid()
        if parent_data["email"].lower() == student_data["email"].lower():
            return Response(
                data={"email": "Student and parent cannot have same email address"}, status=status.HTTP_400_BAD_REQUEST,
            )

        if not (parent_valid and student_valid):
            data = {}
            data.update(parent_serializer.errors)
            data.update(student_serializer.errors)
            return Response(data=data, status=status.HTTP_400_BAD_REQUEST)
        # All set. Create and invite our users
        parent = parent_serializer.save()
        parent.registration_timezone = request.data.get("timezone")
        parent.save()
        student = student_serializer.save()
        student_manager = StudentManager(student)
        student = student_manager.set_parent(parent)
        # Add student to course. Note that student doesn't get enrolled until they have a package purchase
        # for the course
        student.pending_enrollment_course = course
        student.registration_timezone = request.data.get("timezone")
        student.save()
        sentry_sdk.capture_message(
            f"Student pending enrollment: {student.invitation_name} {student.pk} course: {course.name}"
        )
        if not existing_parent:
            create_notification(parent.user, notification_type="invite")
        if not existing_student:
            create_notification(student.user, notification_type="invite")

        # TODO: Notify admins

        return Response({})


class ObtainJWTLinkView(AccessStudentPermission, View):
    """ Users can use this view to get a link with a valid JWT to login as another user
        Counselors can login as their students or their students' parents
        Admins can login as any user.
    """

    # We redirect different user types to different subdomains (so counselor can be logged in as
    # multiple users at once)
    REDIRECT_DOMAINS = {
        user_types.STUDENT: settings.LOGIN_LINK_SITE_URL,
        user_types.PARENT: settings.LOGIN_LINK_SITE_URL,
    }

    def get(self, request, user_type, uuid, *args, **kwargs):
        """ Arguments:
                user_type 'student' is only supported option at this time
                uuid UUID slug of Student user is trying to login as
        """
        if user_type == user_types.STUDENT:
            student = Student.objects.filter(slug=uuid).first()
            if not student or not request.user.is_authenticated or not self.has_access_to_student(student):
                return HttpResponseForbidden()
            # User has permission to obtain this link. Let's do it!
            token = str(RefreshToken.for_user(student.user).access_token)
            redirect_url = f'{self.REDIRECT_DOMAINS[student.user_type]}{reverse("platform", kwargs={"platform_type": student.user_type})}?t={token}'
        elif user_type == user_types.PARENT:
            parent = Parent.objects.filter(slug=uuid).first()
            if not parent or not request.user.is_authenticated or not self.has_access_to_parent(parent):
                return HttpResponseForbidden()
            token = str(RefreshToken.for_user(parent.user).access_token)
            redirect_url = f'{self.REDIRECT_DOMAINS[parent.user_type]}{reverse("platform", kwargs={"platform_type": parent.user_type})}?t={token}'
        else:
            return HttpResponseBadRequest(f"Invalid user type {user_type}")
        return HttpResponseRedirect(redirect_url)


class SwitchLinkedUserView(View):
    """ Tutors and Counselors who are also admins can use this view to switch between their tutor/counselor
        account and their admin account.
        Tutors and counselors who are also admins have their user.linked_administrator property set.
        Arguments:
            user_type URL kwarg: Either administrator, tutor, or counselor; the type of user we want to switch TO
    """

    def get(self, request, user_type, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()
        if user_type == user_types.ADMINISTRATOR:
            # We're logged in as the linked user, check to make sure there's an associated administrator
            if not hasattr(request.user, "linked_administrator"):
                return HttpResponseForbidden()
            login_user = request.user.linked_administrator.user
        else:
            # We are logged in as the hidden user associated with an Administrator, and need to switch to that
            # Administrator's linked_user
            login_user = User.objects.filter(linked_administrator__user=request.user).first()
            if not login_user:
                return HttpResponseForbidden()
        if not login_user.is_active:
            return HttpResponseForbidden()
        # Login as login user, then hit the platform view
        logout(request)
        login(request, login_user, backend="django.contrib.auth.backends.ModelBackend")
        return HttpResponseRedirect(f'{reverse("platform", kwargs={"platform_type": user_type})}')


class LogoutView(View):
    """ Log user out upon GET """

    def get(self, request):
        logout(request)
        return HttpResponseRedirect(reverse("cw_login"))
