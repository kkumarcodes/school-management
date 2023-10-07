import os
from django.urls.base import reverse
import yaml
from requests_oauthlib import OAuth2Session
from django.conf import settings

# This is necessary for testing with non-HTTPS localhost
# Remove this if deploying to production
if settings.ENV != "production":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# This is necessary because Azure does not guarantee
# to return scopes in the same case and order as requested
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
os.environ["OAUTHLIB_IGNORE_SCOPE_CHANGE"] = "1"


# Helper function to load our Azure app settings, and inject env vars as needed
def _get_settings() -> dict:
    with open(os.path.join(settings.BASE_DIR, "settings", "ms_oauth.yml")) as f:
        app_settings = yaml.load(f, yaml.SafeLoader)
    app_settings["app_secret"] = settings.MS_APP_SECRET
    app_settings["redirect"] = f"{settings.SITE_URL}{reverse('outlook-callback')}"
    return app_settings


# Method to generate a sign-in url
def get_sign_in_url():
    app_settings = _get_settings()
    authorize_url = "{0}{1}".format(app_settings["authority"], app_settings["authorize_endpoint"])
    # Initialize the OAuth client
    aad_auth = OAuth2Session(
        app_settings["app_id"], scope=app_settings["scopes"], redirect_uri=app_settings["redirect"]
    )

    sign_in_url, state = aad_auth.authorization_url(authorize_url, prompt="login")

    return sign_in_url, state


# Method to exchange auth code for access token
def get_token_from_code(callback_url, expected_state):
    app_settings = _get_settings()
    # Initialize the OAuth client
    aad_auth = OAuth2Session(
        app_settings["app_id"],
        state=expected_state,
        scope=app_settings["scopes"],
        redirect_uri=app_settings["redirect"],
    )
    token_url = "{0}{1}".format(app_settings["authority"], app_settings["token_endpoint"])
    token = aad_auth.fetch_token(
        token_url, client_secret=app_settings["app_secret"], authorization_response=callback_url
    )

    return token
