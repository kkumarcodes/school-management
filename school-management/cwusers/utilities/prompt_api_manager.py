""" This module contains utilities for interacting with the Prompt API
    Note that when testing (settings.TESTING) we use specific test users
"""
import json
import requests
import sentry_sdk
from django.conf import settings
from snusers.models import Student, Counselor


class PromptAPIManagerException(Exception):
    pass


JWT_ENDPOINT = "/user/token/"
TEST_SCHOOL_LIST = ["123961", "110662", "164988", "170976", "110705", "236948", "110635", "126614", "193900", "110680"]
TEST_STUDENT_SLUG = "ce80f4c6-57b4-45fe-8f11-87b23803eff6"
TEST_COUNSELOR_SLUG = "d4daacd1-3ff8-4a5e-8e90-57bf5f3e7373"


class PromptAPIManager:
    def __init__(self):
        if not (settings.PROMPT_API_BASE and settings.PROMPT_API_TOKEN):
            raise PromptAPIManagerException("Missing Prompt API Details")

    def obtain_jwt(self, cwuser):
        """ Obtain a JSON web token for either a student or counselor.
            Arguments:
                cwuser must be a counseling Student or a Counselor
            Returns:
                JWT
        """

        data = {
            "user_id": str(cwuser.slug),
            "first_name": cwuser.user.first_name if cwuser.user.first_name else " ",
            "last_name": cwuser.user.last_name if cwuser.user.last_name else " ",
            "email": cwuser.user.email,
        }
        if isinstance(cwuser, Student):
            data["counselor_id"] = str(cwuser.counselor.slug)
            data["organization_id"] = str(cwuser.counselor.slug)
            data["user_type"] = "student"
            # data["schools"] = list(cwuser.student_university_decisions.values_list("university__iped", flat=True))
            if settings.TESTING:
                data["user_id"] = TEST_STUDENT_SLUG
                data["counselor_id"] = TEST_COUNSELOR_SLUG
                data["organization_id"] = TEST_COUNSELOR_SLUG
        elif isinstance(cwuser, Counselor):
            data["organization_id"] = str(cwuser.slug)
            data["user_type"] = "counselor"
            if settings.TESTING:
                data["user_id"] = TEST_COUNSELOR_SLUG
                data["organization_id"] = TEST_COUNSELOR_SLUG
        else:
            raise PromptAPIManagerException("Invalid user type for Prompt JWT")

        url = f"{settings.PROMPT_API_BASE}{JWT_ENDPOINT}"

        response = requests.post(url, json=data, headers={"Authorization": f"Token {settings.PROMPT_API_TOKEN}"})
        if response.status_code != 200:
            with sentry_sdk.configure_scope() as scope:
                scope.set_context(
                    "Prompt API JWT Request",
                    {"data": data, "status": response.status_code, "response": response.content},
                )
                ex = PromptAPIManagerException("Prompt API Error (Obtain JWT)")
                sentry_sdk.capture_exception(ex)
                if settings.DEBUG or settings.TESTING:
                    print(f"Prompt API Manager response {response.status_code}")
                    print(response.content)
                raise ex
        result = json.loads(response.content)
        return result["access"]
