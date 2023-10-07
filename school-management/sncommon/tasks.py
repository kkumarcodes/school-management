from datetime import timedelta

from celery import shared_task
from sncommon.utilities.magento import MagentoAPIManager, MagentoAPIManagerException
from sntutoring.models import StudentTutoringSession
from sntutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from snusers.models import Counselor, Tutor
from snusers.utilities.graph_helper import sync_outlook
from django.conf import settings
from django.utils import timezone


@shared_task
def health_check_task():
    """ Just logs current version
    """
    print(f"Health Check Task. Version: {settings.VERSION}")
    return [str(settings.VERSION)]


@shared_task
def charge_paygo_sessions(charge=True):
    """ Charge past paygo sessions that were not paid for
        Arguments:
            charge {boolean} Whether or not to actually execute charges
    """

    sessions = (
        StudentTutoringSession.objects.filter(
            student__is_paygo=True,
            paygo_transaction_id="",
            set_cancelled=False,
            end__lt=timezone.now() - timedelta(hours=1),
            end__gt=timezone.now() - timedelta(hours=25),
            is_tentative=False,
        )
        .exclude(student__last_paygo_purchase_id="")
        .distinct()
    )
    charged_sessions = []
    errors = []
    for session in sessions:
        student_mgr = StudentTutoringPackagePurchaseManager(session.student)
        hours = student_mgr.get_available_hours()
        # Look for negative hours of type, which means family has not paid for session yet
        charge_session = False
        if (
            session.session_type == StudentTutoringSession.SESSION_TYPE_CURRICULUM
            and hours["individual_curriculum"] < 0
        ):
            charge_session = True
        elif (
            session.session_type == StudentTutoringSession.SESSION_TYPE_TEST_PREP and hours["individual_test_prep"] < 0
        ):
            charge_session = True
        if charge_session:
            try:
                mgr = StudentTutoringPackagePurchaseManager(session.student)
                tutoring_package = mgr.get_paygo_tutoring_package(session)
                if settings.TESTING:
                    MagentoAPIManager.create_paygo_purchase(session, tutoring_package)
                elif charge:
                    # Not yet ready to actually execute payments
                    MagentoAPIManager.create_paygo_purchase(session, tutoring_package)
                charged_sessions.append(session.pk)
            except MagentoAPIManagerException as e:
                if settings.TESTING:
                    print(e)
                errors.append(session.pk)
    return {"charged": charged_sessions, "errors": errors, "charge": charge}


@shared_task
def sync_outlook_with_schoolnet():
    """ For all active tutors and counselors with a microsoft_token,
    call sync_outlook utility method to ensure all meetings are on their
    outlook calendar
    """
    [sync_outlook(x) for x in Counselor.objects.exclude(microsoft_token="")]
    [sync_outlook(x) for x in Tutor.objects.exclude(microsoft_token="")]
