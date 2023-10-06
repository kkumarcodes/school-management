from rest_framework_simplejwt.authentication import JWTAuthentication


class JWTSpecifyTokenAuthentication(JWTAuthentication):
    """
		A version of JWTAUthentication that looks for the token in GET['t'] instead
		of in Auth header
		Overrides JWT authentication:
		https://github.com/davesque/django-rest-framework-simplejwt/blob/master/rest_framework_simplejwt/authentication.py
	"""

    def authenticate(self, request):
        """ Override authenticate to pull token from GET param """
        raw_token = request.GET.get("t")
        if raw_token:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), None
        return None, None

