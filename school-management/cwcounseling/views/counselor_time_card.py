from django.db.models import query
import sentry_sdk
from datetime import datetime, timedelta
from django.db.models.query_utils import Q
from django.utils import dateparse, timezone
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import status

from cwcounseling.constants import counseling_student_types
from cwcounseling.models import CounselingHoursGrant, CounselorTimeCard, CounselorTimeEntry
from cwcounseling.serializers.counselor_meeting import (
    CounselingHoursGrantSerializer,
    CounselorTimeEntrySerializer,
    CounselorTimeCardSerializer,
)
from cwcounseling.serializers.student_counseling_hours import StudentCounselingHoursSerializer

from cwcommon.mixins import AdminContextMixin, CSVMixin
from cwcounseling.utilities.counselor_time_card_manager import (
    CounselorTimeCardManager,
    CounselorTimeCardManagerException,
)
from snusers.mixins import AccessStudentPermission
from snusers.models import Counselor, Student
from itertools import groupby
from django.http import HttpResponse
import csv
import dateutil.parser


class CounselingHoursGrantViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """ CRUD for CounselingHoursGrant. Only admin can write; any user with access to student
        can read
        Supported query params:
            ?student (get all grants for a specific student)
        If ?student not provided, then we return all objects for admin; all object for all of a counselor's
        students if the logged-in user is a counselor.
    """

    queryset = CounselingHoursGrant.objects.all().select_related("student")
    serializer_class = CounselingHoursGrantSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super().check_permissions(request)
        is_admin = hasattr(request.user, "administrator")
        is_admin_or_counselor = is_admin or hasattr(request.user, "counselor")
        if self.request.method != "GET" and not is_admin:
            self.permission_denied(request)

        # If not admin/counselor, then we require that a student is specified and that user has access to that student
        if not is_admin_or_counselor and not request.query_params.get("student"):
            self.permission_denied("Must specify student to load hours grants for")

        if request.query_params.get("student"):
            student = get_object_or_404(Student, pk=request.query_params["student"])
            # If user is not admin/counselor, then student must be paygo for them to see hours
            if (not is_admin_or_counselor) and not student.is_paygo:
                self.permission_denied(request, message="Student is not Paygo")

            if not self.has_access_to_student(student):
                self.permission_denied(request)

    def filter_queryset(self, queryset):
        query_params = self.request.query_params
        if query_params.get("student"):
            queryset = queryset.filter(student__id=query_params["student"])
        elif hasattr(self.request.user, "administrator"):
            pass
        elif hasattr(self.request.user, "counselor"):
            queryset = queryset.filter(student__counselor__user=self.request.user)
        elif hasattr(self.request.user, "student"):
            queryset = queryset.filter(student__user=self.request.user)
        else:
            # Shouldn't hit this case, but failsafe just in case to ensure we don't expose unnecessary data
            return CounselingHoursGrant.objects.none()

        if not self.kwargs.get("pk"):
            if self.request.query_params.get("start"):
                queryset = queryset.filter(created__gte=dateparse.parse_date(self.request.query_params.get("start")))
            if self.request.query_params.get("end"):
                queryset = queryset.filter(created__lte=dateparse.parse_date(self.request.query_params.get("end")))

        return queryset

    def perform_create(self, serializer):
        grant: CounselingHoursGrant = serializer.save()
        grant.created_by = self.request.user
        grant.save()


class CounselorTimeEntryViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """ CRUD access for Counselor and Admin.
    Counselor can CREATE and UPDATE.
        UPDATE only for their own time entry.
        CREATE only for their student (or no student)

        For retrieving, endpoint accepts query params:
                counselor
                student
                counselor_time_card: All time entries associated with a particular CounselorTimeCard
                date range: start and end, as datetime. Defaults to previous 2 weeks if this is not provided AND
                    time ard not provided
                paygo: If "true", then only Paygo students (is_paygo or PAYGO package) returned
                paid: If "true", then only paid time entries are included. If "false" then only unpaid time entries
                    are included

    """

    queryset = CounselorTimeEntry.objects.all()
    serializer_class = CounselorTimeEntrySerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super().check_permissions(request)
        is_admin_or_counselor = hasattr(request.user, "administrator") or hasattr(request.user, "counselor")
        if self.request.method == "GET" and self.request.query_params.get("student") and not is_admin_or_counselor:
            student = get_object_or_404(Student, pk=self.request.query_params["student"])
            if not self.has_access_to_student(student):
                self.permission_denied(request)
            return True

        if not is_admin_or_counselor:
            self.permission_denied(request)

        # if a student is specified, deny request if not this counselor's student
        if hasattr(request.user, "counselor") and request.data.get("student"):
            student = get_object_or_404(Student, pk=request.data["student"])
            if student:
                if student.counselor != request.user.counselor:
                    self.permission_denied(request)

    def check_object_permissions(self, request, obj: CounselorTimeEntrySerializer):
        super().check_object_permissions(request, obj)
        if hasattr(request.user, "administrator"):
            return True
        if (
            hasattr(request.user, "counselor")
            and obj.counselor == request.user.counselor
            and not obj.student
            or (obj.student.counselor and obj.student.counselor == request.user.counselor)
        ):
            return True
        self.permission_denied(request)

    def filter_queryset(self, queryset):
        # if counselor, first filter for their entries that either have no
        # associate student or it is their student
        counselor = self.request.query_params.get("counselor")
        student = self.request.query_params.get("student")

        if hasattr(self.request.user, "counselor"):
            queryset = queryset.filter(
                Q(counselor=self.request.user.counselor)
                | Q(student__counselor=self.request.user.counselor)
                | Q(counselor_time_card__counselor=self.request.user.counselor)
            )
        if self.request.query_params.get("counselor_time_card"):
            queryset = queryset.filter(counselor_time_card=self.request.query_params["counselor_time_card"])
        elif not self.kwargs.get("pk"):
            # default to last 2 weeks if no start/end provided and no time card provided
            start = (
                dateparse.parse_date(self.request.query_params.get("start"))
                if self.request.query_params.get("start")
                else timezone.now() - timedelta(days=14)
            )
            end = (
                dateparse.parse_date(self.request.query_params.get("end"))
                if self.request.query_params.get("end")
                else timezone.now()
            )
            queryset = queryset.filter(date__lte=end, date__gte=start)
        if self.request.query_params.get("paygo") == "true":
            queryset = queryset.filter(student__counseling_student_types_list__icontains=counseling_student_types.PAYGO)
        if student:
            queryset = queryset.filter(student=student)
        if counselor:
            queryset = queryset.filter(counselor=counselor)
        if self.request.query_params.get("paid") == "true":
            queryset = queryset.filter(Q(marked_paid=True) | Q(amount_paid__gt=0))
        elif self.request.query_params.get("paid") == "false":
            queryset = queryset.filter(marked_paid=False).exclude(amount_paid__gt=0)
        return queryset.select_related("student", "counselor")

    def perform_create(self, serializer):
        """ Create new time entry for a specific counselor.
            Arguments:
                counselor
                created_by
                student (optional)
                date
                hours (time to log)
            Return:
                new CounselorTimeEntry object
        """
        counselor = None
        if hasattr(self.request.user, "counselor"):
            counselor = self.request.user.counselor
        elif self.request.data.get("counselor"):
            counselor = get_object_or_404(Counselor, pk=self.request.data["counselor"])
        elif self.request.data.get("student"):
            counselor = get_object_or_404(Counselor, students=self.request.data["student"])
        created_by = self.request.user
        counselor_time_entry: CounselorTimeEntry = serializer.save()
        counselor_time_entry.created_by = created_by
        counselor_time_entry.counselor = counselor
        if not counselor_time_entry.date:
            counselor_time_entry.date = timezone.now()
        counselor_time_entry.save()

        return counselor_time_entry

    def perform_destroy(self, instance: CounselorTimeEntry):
        time_card = instance.counselor_time_card
        response = super().perform_destroy(instance)
        if time_card:
            mgr = CounselorTimeCardManager(time_card)
            mgr.set_total()
        return response

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.query_params.get("format") == "csv":
            ctx["format"] = "csv"
        return ctx


class CounselorTimeCardViewset(CSVMixin, AdminContextMixin, ModelViewSet):
    queryset = CounselorTimeCard.objects.all()
    serializer_class = CounselorTimeCardSerializer

    def check_permissions(self, request):
        if not (hasattr(self.request.user, "administrator") or hasattr(self.request.user, "counselor")):
            self.permission_denied(request)
        return super().check_permissions(request)

    def check_object_permissions(self, request, obj: CounselorTimeCard):
        if hasattr(self.request.user, "counselor") and obj.counselor != self.request.user.counselor:
            self.permission_denied(request)
        if request.method.lower() == "delete" and not hasattr(self.request.user, "administrator"):
            self.permission_denied(request)
        return super().check_object_permissions(request, obj)

    def update(self, request, *args, **kwargs):
        """ We do not allow updating a time card directly. It can be updated by approving
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def create(self, request, *args, **kwargs):
        """ Create a new time card. We do not user the serializer for this. Instead, we use the manager.
            Arguments (all required):
                counselors {PK[]} List of PKs of counselors to create time card for
                start {date string}
                end {date string}
        """
        start = dateparse.parse_date(request.data.get("start"))
        end = dateparse.parse_date(request.data.get("end"))

        if not (start and end):
            raise ValidationError("Invalid start/end to create counselor time card")

        end = datetime(end.year, end.month, end.day, 23, 59)  # We use end of day
        start = datetime(start.year, start.month, start.day)

        time_cards = []
        for counselor_pk in request.data.get("counselors"):
            counselor: Counselor = get_object_or_404(Counselor, pk=counselor_pk)
            # Time cards can only be created for part time counselors
            if not counselor.part_time:
                continue
            try:
                time_card = CounselorTimeCardManager.create(counselor, start, end)
                time_cards.append(time_card)
            except CounselorTimeCardManagerException as err:
                if settings.DEBUG:
                    print(err)
                else:
                    sentry_sdk.capture_exception(err)

        if request.data.get("counselors") and not time_cards:
            # We return error only if we were supposed to create time cards and none were created
            return Response({"detail": "Unable to create time cards"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(time_cards, many=True).data, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True)
    def approve(self, request, *args, **kwargs):
        """ Counselor or tutor approving a time card. We infer what type of approval it is by the
            type of user on request.
            request.data:
                note {str} Optional Approval Note
            Returns updated CounselorTimeCard
        """
        time_card: CounselorTimeCard = self.get_object()
        mgr = CounselorTimeCardManager(time_card)
        try:
            if hasattr(request.user, "administrator"):
                time_card = mgr.approve_as_admin(note=request.data.get("note"))
            elif hasattr(request.user, "counselor"):
                time_card = mgr.approve_as_counselor(note=request.data.get("note"))
            else:
                raise ValidationError("Only admin or counselor can approve")
        except CounselorTimeCardManagerException as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance=time_card).data)

    def filter_queryset(self, queryset):
        """ We support filtering on the following params:
                start (date string)
                end (date string)
                counselor (pk)
        """
        queryset = super().filter_queryset(queryset)
        if hasattr(self.request.user, "counselor"):
            queryset = queryset.filter(counselor=self.request.user.counselor)
        if self.request.query_params.get("start") and dateparse.parse_date(self.request.query_params["start"]):
            queryset = queryset.filter(start__gte=dateparse.parse_date(self.request.query_params["start"]))
        if self.request.query_params.get("end") and dateparse.parse_date(self.request.query_params["end"]):
            queryset = queryset.filter(
                end__lte=dateparse.parse_date(self.request.query_params["end"]) + timedelta(days=1)
            )
        if self.request.query_params.get("counselor"):
            queryset = queryset.filter(counselor=self.request.query_params["counselor"])
        return queryset

    @action(methods=["GET"], detail=False, url_path="csv-by-payrate", url_name="csv_by_payrate")
    def get__CSV_by_payrate(self, request, *args, **kwargs):
        """
        - admin can export a CSV of counselor time cards with a break down of hours by pay rate
        - query params:
                start (datetime ISO strings(e.g 2011-08-15T10:00:36.402Z))
                end (datetime ISO strings)
        """
        if not (request.GET.get("start") and request.GET.get("end")):
            raise ValidationError(detail="Start and end dates (query params) required")
        start = dateutil.parser.isoparse(request.GET.get("start")).replace(hour=0, minute=0, second=0, microsecond=0)
        end = dateutil.parser.isoparse(request.GET.get("end")).replace(hour=0, minute=23, second=59, microsecond=999999)
        time_cards = CounselorTimeCard.objects.filter(end__gte=start, end__lte=end)
        time_card_entries = CounselorTimeEntry.objects.filter(counselor_time_card__in=time_cards)

        def get_pay_rate_for_time_entry(entry):
            pay_rate = entry.counselor_time_card.hourly_rate
            if entry.pay_rate:
                pay_rate = entry.pay_rate
            elif entry.student and entry.student.counselor_pay_rate:
                pay_rate = entry.student.counselor_pay_rate
            return pay_rate

        def get_group_key(entry: CounselorTimeEntry):
            rate = get_pay_rate_for_time_entry(entry)
            return f"{entry.counselor_time_card.pk}__{rate}"

        grouped_entries = groupby(sorted(time_card_entries, key=get_group_key), key=get_group_key)
        grouped_entries_dict = {}
        for key, group in grouped_entries:
            grouped_entries_dict[key] = list(group)

        headers = ["Counselor", "Counselor is Part Time", "Start", "End", "Created", "Total Hours", "Total Pay"]
        pay_rate_list = sorted({k.split("__")[1] for k in grouped_entries_dict.keys()})
        headers += [f"Hours at ${x}" for x in pay_rate_list]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="CounselorTimeCardPayrateBreakdown.csv"'
        writer = csv.DictWriter(response, headers)
        writer.writeheader()
        for tc in time_cards:
            row = {
                "Counselor": tc.counselor.name,
                "Start": tc.start.strftime("%Y-%m-%d"),
                "End": tc.end.strftime("%Y-%m-%d"),
                "Created": tc.created.strftime("%Y/%m/%d, %H:%M:%S"),
                # "Counselor Pay Rate": tc.counselor.pay_rate,
                "Total Hours": tc.total_hours,
                "Total Pay": tc.total,
                "Counselor is Part Time": tc.counselor.part_time,
            }
            for rate in pay_rate_list:
                row[f"Hours at ${rate}"] = 0
                entries = grouped_entries_dict.get(f"{tc.pk}__{rate}")
                if entries:
                    row[f"Hours at ${rate}"] = sum([entry.hours for entry in entries])

            writer.writerow(row)

        return response


class StudentCounselingHoursViewset(CSVMixin, ModelViewSet):
    """ GET Student counseling hours(hours grant and hours spent) as CSV
    """

    queryset = Student.objects.filter(counseling_hours_grants__isnull=False).select_related("counselor").distinct()
    serializer_class = StudentCounselingHoursSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super().check_permissions(request)
        is_admin = hasattr(request.user, "administrator")
        if self.request.method != "GET" or not is_admin:
            self.permission_denied(request)

    def get_renderer_context(self):
        context = super().get_renderer_context()
        # force the order from the serializer, by default order of fields is alphabatical
        context["header"] = self.serializer_class.Meta.fields
        return context

    def filter_queryset(self, queryset):
        return queryset

