""" Utility for managing zoom accounts, and their relationship to CWUser accounts
"""
import json
import requests
from django.conf import settings
from cwusers.models import ZoomFields

USER_ENDPOINT = "https://api.zoom.us/v2/users"
PRO_ZOOM_URLS = [
    "https://zoom.us/j/2856139883",
    "https://us02web.zoom.us/j/3236335094",
    "https://us02web.zoom.us/j/9565227041",
    "https://us02web.zoom.us/j/8681069581",
    "https://us02web.zoom.us/j/3599857681",
]
if settings.TESTING:
    PRO_ZOOM_URLS = [
        "https://zoom.us/j/0",
        "https://zoom.us/j/1",
        "https://us02web.zoom.us/j/2",
        "https://us02web.zoom.us/j/3",
        "https://us02web.zoom.us/j/4",
        "https://us02web.zoom.us/j/5",
        "https://us02web.zoom.us/j/6",
        "https://us02web.zoom.us/j/7",
    ]


class ZoomManagerException(Exception):
    pass


TEST_DATA = {
    "pmi": "TEST",
    "personal_meeting_url": "TEST",
    "phone_number": "TEST",
    "id": "TEST",
    "type": 1,
}


class ZoomManager:
    client = None

    def __init__(self):
        if not (settings.TESTING or settings.ZOOM_API_JWT):
            raise ZoomManagerException("Missing Zoom API Details")
        self.header = {
            "Authorization": f"Bearer {settings.ZOOM_API_JWT}",
            "Content-Type": "application/json;charset=UTF-8",
        }

    def get_zoom_user(self, cwuser):
        """ Attempt to retrieve a Zoom user with same email address as cwuser. If zoom user exists,
            Zoom fields on cwuser are updated and updated user is returned. Otherwise, False is returned.
            Arguments:
                cwuser {Tutor|Counselor} User we're attempting to retrieve associated zoom user for.
        """

        if not isinstance(cwuser, ZoomFields):
            raise ZoomManagerException("Invalid user")
        if settings.TESTING:
            status_code = 200
            result = TEST_DATA
        else:
            response = requests.get(f"{USER_ENDPOINT}/{cwuser.user.email}", headers=self.header)
            status_code = response.status_code
            result = json.loads(response.content) if status_code == 200 else None
        if status_code == 404:
            """ ERROR HAPPENING HERE
            """
            print("Zoom 404")
            return False
        if status_code == 200:
            print("Zoom user details", result)
            cwuser.zoom_pmi = result.get("pmi", "")
            cwuser.zoom_url = result.get("personal_meeting_url", "")
            cwuser.zoom_phone = result.get("phone_number", "")
            cwuser.zoom_user_id = result["id"]
            cwuser.zoom_type = result["type"]
            cwuser.save()
            return cwuser
        else:
            print(response.status_code, response.content)
            # TODO: Add error tracking meta to sentry scope
            raise ZoomManagerException(f"Bad response from zoom API: {response.status_code}")

    def create_zoom_user(self, cwuser):
        """ Create a new zoom user for cwuser. Before running this, we use get_zoom_user to check and
            see if zoom user already exists. If they do, then cwuser will get updated (result of
            get_zoom_user) otherwise user will get invited and Zoom user ID will get associated with cwuser.
            Arguments:
                cwuser {Tutor|Counselor} User we're attempting to retrieve associated zoom user for.
            Returns:
                updated cwuser, with Zoom ID and (if user already existed in Zoom) other Zoom fields complete
        """
        if not isinstance(cwuser, ZoomFields):
            raise ZoomManagerException("Invalid user")
        updated_user = self.get_zoom_user(cwuser)
        # Note that we could get back a user without a URL. That means the user is pending creating their zoom
        # account. We should reinvite them.
        if updated_user and updated_user.zoom_url:
            return updated_user

        # User doesn't exist. Let's try to make them
        data = {
            "action": "create",
            "user_info": {
                "email": cwuser.user.email,
                "type": ZoomFields.ZoomTypes.ZOOM_TYPE_BASIC,
                "first_name": cwuser.user.first_name,
                "last_name": cwuser.user.last_name,
            },
        }
        if settings.TESTING:
            status_code = 201
            result = {"id": TEST_DATA["id"]}
        else:
            response = requests.post(USER_ENDPOINT, json.dumps(data), headers=self.header)
            status_code = response.status_code
            result = json.loads(response.content)
        if status_code == 201:
            cwuser.zoom_id = result.get("id")
            cwuser.save()
            return cwuser
        else:
            print(response.status_code, response.content)
            # TODO: Add error tracking meta to sentry scope
            raise ZoomManagerException(f"Bad response from zoom API: {response.status_code}")
