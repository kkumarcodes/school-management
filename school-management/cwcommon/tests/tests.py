""" Test our health check and error views
    python manage.py test cwcommon.tests
"""
from django.test import TestCase
from django.shortcuts import reverse
from django.conf import settings


class TestHealthCheckError(TestCase):
    def test_health_check(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)

    def test_throw_exception(self):
        self.assertRaises(
            ValueError, lambda: self.client.get(reverse("throw_exception"))
        )
