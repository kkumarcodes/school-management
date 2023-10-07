from rest_framework.generics import RetrieveAPIView
from rest_framework.authentication import TokenAuthentication
from snusers.serializers.prompt import PromptCounselorSerializer, PromptStudentSerializer, PromptOrganizationSerializer
from snusers.models import Student, Counselor
from snusers.permissions import IsAdminOrPrompt


class PromptStudentAPIView(RetrieveAPIView):
    serializer_class = PromptStudentSerializer
    queryset = Student.objects.filter(counselor__isnull=False, counselor__prompt=True, is_prompt_active=True,)
    authentication_classes = (TokenAuthentication,)  # API Only
    permission_classes = (IsAdminOrPrompt,)
    lookup_field = "slug"
    lookup_url_kwarg = "slug"


class PromptCounselorAPIView(RetrieveAPIView):
    serializer_class = PromptCounselorSerializer
    queryset = Counselor.objects.all()
    authentication_classes = (TokenAuthentication,)  # API Only
    permission_classes = (IsAdminOrPrompt,)
    lookup_field = "slug"
    lookup_url_kwarg = "slug"


class PromptOrganizationAPIView(RetrieveAPIView):
    serializer_class = PromptOrganizationSerializer
    queryset = Counselor.objects.all()
    authentication_classes = (TokenAuthentication,)  # API Only
    permission_classes = (IsAdminOrPrompt,)
    lookup_field = "slug"
    lookup_url_kwarg = "slug"
