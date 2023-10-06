""" Utility for interacting with the Hubspot API
"""
import json
from os import path
from datetime import timedelta
import requests

from sentry_sdk import configure_scope, capture_exception
from django.conf import settings
from django.utils import timezone
from cwusers.models import Student, Parent

HUBSPOT_COUNSELOR_MAP = {
    "0": "Please select a counselor",
    "6": "Abby van Geldern",
    "7": "Amy Chatterjee",
    "8": "Breanne Boyle",
    "9": "Cara Camire",
    "10": "Casey Near",
    "11": "Darcy Hoberman",
    "13": "Eva Dodds",
    "14": "Jazzmin Lu",
    "15": "Jennifer Turano",
    "16": "Test User",
    "19": "Paige Peterkin",
    "20": "Nan Yuasa",
    "21": "Rhiannon Schade",
    "22": "Nikayla Loy",
    "23": "Jordan Kanarek",
    "24": "Monica Rude",
    "25": "Meredith Graham",
    "26": "Kailey Hockridge",
    "27": "Katie Sprague",
    "28": "Nicole Pilar",
    "29": "Michael Banks",
    "30": "Noor Haddad",
    "31": "Megan Carlier",
    "32": "Jenny Peacock",
    "33": "Laura Dicas",
    "34": "Rebecca Putter",
    "35": "Liz Pack",
    "36": "Tim Magee",
    "37": "Nick Manuszak",
    "38": "Tom Barry",
    "39": "Tara Wessel Swoboda",
    "40": "Leigh Weissman",
    "41": "Lisa Caruso",
    "42": "Liz Marx",
    "43": "Chelsea Block",
    "44": "Allison Lopour",
    "45": "Arun Ponnusamy",
    "48": "Maureen Gelberg",
    "50": "Kavin Buck",
    "54": "Paul Kanarek",
    "62": "Matt Musico",
    "63": "Judy Lee",
    "64": "Davin Sweeney",
    "66": "Kirsten Hanson-Press",
    "70": "Rahsaan Burroughs",
    "71": "Julie Simon",
    "73": "Sara Gordon",
    "74": "Kelsey De Haan",
    "75": "Monica Brown",
    "76": "Lindsay O'Sullivan",
    "77": "Sandi Zwick",
    "78": "Nandita Gupta",
    "79": "Katherine Folkman",
    "80": "Kellie Graham",
    "81": "Michal Goldstein",
    "82": "Joe Korfmacher",
    "83": "Christina Mangano",
    "84": "Katie Konrad Moore",
    "85": "Kristin Sullivan",
    "86": "Meg Mahoney",
    "87": "Nicole Oringer",
    "88": "Becky Motta",
    "89": "Nancy Ciabattari",
    "90": "Laura Cavanaugh",
    "91": "Kathleen DeLuca",
    "92": "Robyn Solomon",
    "93": "Leslie Levy",
    "95": "Ashley Nieblas",
    "96": "Torrey Eason",
    "98": "Susan Gurley",
    "99": "Leslie Tam",
    "100": "Annie Behari",
    "101": "Kristin White",
    "102": "Patti Miller",
    "103": "Emily Selden",
    "104": "Ian Parker",
    "105": "Kim Haselhoff",
    "110": "Margaret Carter",
    "111": "Sarah Turner",
    "112": "Maureen Hinkis",
    "113": "Sydney Matthes",
    "114": "Susan Ruszala",
    "115": "Sherri Buchanan",
    "116": "Pam Chirls",
    "117": "Jill Stueck",
    "118": "Hani Rahman",
    "120": "Grant Cushman",
    "122": "Roslyn Estrada",
    "123": "Rachel Will",
    "124": "Vince Valenzuela",
    "141": "Christopher Logan",
    "153": "Jon Tarella",
    "154": "Jon Tarella Online",
    "155": "Michal Goldstein Online",
    "158": "Liz Gyori",
    "159": "Veronica Leyva",
    "164": "Anita Gajula",
    "Colleen Boucher-Robinson": "Colleen Boucher-Robinson",
    "Marisela Gomez": "Marisela Gomez",
    "Tim Townley": "Tim Townley",
}


class HubspotManagerException(Exception):
    pass


HUBSPOT_JWT_ENDPOINT = "https://api.hubapi.com/oauth/v1/token"

PORTAL_ID = "3298693"
HUBSPOT_FORMS = {"registration": "6dd18223-e666-4814-8879-3aef2d86bebe"}


class HubspotManager:
    def __init__(self):
        if not (settings.HUBSPOT_APP_ID and settings.HUBSPOT_APP_SECRET):
            raise HubspotManagerException("Missing hubspot settings")

    def obtain_jwt(self, access_code=None, refresh_token=None):
        """ Exchange an access code (from last step of Oauth workflow) for JWT, and store JWT
            in our credentials file
            Step 4: https://developers.hubspot.com/docs/methods/oauth2/oauth2-quickstart
            Arguments:
                acccess_code {string} Access Code from Hubspot (oauth)
            Returns: JWT response object
        """
        if not (access_code or refresh_token):
            raise HubspotManagerException("Access code or refresh required to get JWT")
        response = requests.post(
            HUBSPOT_JWT_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.HUBSPOT_APP_ID,
                "client_secret": settings.HUBSPOT_APP_SECRET,
                "redirect_uri": settings.HUBSPOT_REDIRECT_URI,
                "code": access_code,
            },
        )

        if response.status_code != 200:
            print(response.status_code, response.content)
            raise HubspotManagerException("Unexpected response from HubspotManager")

        result = json.loads(response.content)
        result["expires"] = (timezone.now() + timedelta(minutes=350)).isoformat()

        with open(settings.HUBSPOT_CREDENTIALS, "w+") as file_handle:
            file_handle.write(json.dumps(result))
        return result

    def refresh_hubspot_jwt(self):
        """ Use refresh token to obtain new JWT pair from Hubspot """
        if not path.exists(settings.HUBSPOT_CREDENTIALS):
            raise HubspotManagerException("Cannot obtain JWT pair w/o Hubspot credentials")
        with open(settings.HUBSPOT_CREDENTIALS) as file_handle:
            creds = json.loads(file_handle.read())

        return self.obtain_jwt(refresh_token=creds["refresh_token"])


class HubspotFormManager:
    @staticmethod
    def _extract_user_properties(cwuser):
        """ Extract user properties we can update in hubspot from a Student or Parent """
        if not (isinstance(cwuser, Student) or isinstance(cwuser, Parent)):
            raise HubspotManagerException("Can only update student and parents in Hubspot")

        if isinstance(cwuser, Student) and cwuser.parent:
            family_name = f"{cwuser.parent.user.last_name} Family"
        else:
            family_name = f"{cwuser.user.last_name} Family"

        data = {
            "firstname": cwuser.user.first_name,
            "lastname": cwuser.user.last_name,
            "email": cwuser.user.email,
            "address": f"{cwuser.address} {cwuser.address_line_two}",
            "city": cwuser.city,
            "state": cwuser.state,
            "company": family_name,
            "managed_by_wisernet": "true",
        }
        if isinstance(cwuser, Student):
            data["high_school"] = cwuser.high_school
            data["graduation_year"] = cwuser.graduation_year
            data["parent_name_sg"] = cwuser.parent.invitation_name if cwuser.parent else ""
            data["parent_email_2"] = cwuser.parent.user.email if cwuser.parent else ""

        return data

    @staticmethod
    def update_single_contact(cwuser):
        """
            Updat/createse a single Hubspot contact (identified by email)
            This method will raise exception if trying to update IEC student who
            only interacts with whitelabeled platform.

            Request is synchronous
        """
        url = "https://api.hubapi.com/contacts/v1/contact/createOrUpdate/email/%s/?hapikey=%s" % (
            cwuser.user.email,
            settings.HUBSPOT_API_KEY,
        )
        properties = HubspotFormManager._extract_user_properties(cwuser)
        if properties:
            raw_data = {"properties": [{"property": x, "value": y} for (x, y) in properties.items()]}
            user_result = requests.post(json=raw_data, url=url, headers={"Content-type": "application/json"})
            print(user_result, user_result.content, user_result.status_code)
            if user_result.status_code != 200:

                with configure_scope() as scope:
                    scope.set_context("hubspot_api_error", json.loads(user_result.content))
                    capture_exception(HubspotManagerException("Hubspot API failure"))
                return False

            cwuser.hubspot_id = json.loads(user_result.content)["vid"]
            cwuser.save()

            if isinstance(cwuser, Parent) and json.loads(user_result.content)["isNew"]:
                # Create company
                data = {"properties": [{"name": "name", "value": f"{cwuser.user.last_name} Family"}]}
                company_response = requests.post(
                    json=data,
                    url=f"https://api.hubapi.com/companies/v2/companies?hapikey={settings.HUBSPOT_API_KEY}",
                    headers={"Content-type": "application/json"},
                )
                company_data = json.loads(company_response.content)
                if company_response.status_code != 200:
                    print(company_response.content)
                    with configure_scope() as scope:
                        scope.set_context("hubspot_api_error", company_data)
                        capture_exception(HubspotManagerException("Hubspot API failure"))
                    return False

                company_response = requests.put(
                    url=f"https://api.hubapi.com/companies/v2/companies/{company_data['companyId']}/contacts/{cwuser.hubspot_id}?hapikey={settings.HUBSPOT_API_KEY}"
                )
                print("Add to company", company_response.content)
                if company_response.status_code == 200:
                    cwuser.hubspot_company_id = company_data["companyId"]
                    cwuser.save()
                else:
                    print(company_response.content)
            elif isinstance(cwuser, Student) and cwuser.parent and cwuser.parent.hubspot_company_id:
                company_response = requests.put(
                    url=f"https://api.hubapi.com/companies/v2/companies/{cwuser.parent.hubspot_company_id}/contacts/{cwuser.hubspot_id}?hapikey={settings.HUBSPOT_API_KEY}"
                )

            return True
        return False


class HubspotDealManager:
    @staticmethod
    def get_counselor_name(hubspot_deal_id):
        if settings.TESTING:
            return None
        try:
            response = requests.get(
                f"https://api.hubapi.com/deals/v1/deal/{hubspot_deal_id}/?hapikey={settings.HUBSPOT_API_KEY}"
            )
            result = json.loads(response.content)
            if response.status_code == 200 and result.get("properties"):
                prop = result["properties"].get("counselor")
                if not prop:
                    return None
                value = prop.get("value")
                return HUBSPOT_COUNSELOR_MAP[str(value)] if value else None
            else:
                raise HubspotManagerException("Invalid status code")
        except (HubspotManagerException, AttributeError, KeyError) as e:
            with configure_scope() as scope:
                scope.set_context(
                    "hubspot_api_error_deal_properties",
                    {"deal_id": hubspot_deal_id, "result": result, "status_code": response.status_code},
                )
                capture_exception(HubspotManagerException("Hubspot API failure (Deal Props)"))
        return None

