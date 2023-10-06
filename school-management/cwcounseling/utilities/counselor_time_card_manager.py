""" Manager to aid in the creation and editing of CounselorTimeCard objects
"""
from cwcounseling.constants.counselor_time_entry_category import ADMIN_CATEGORIES, ADMIN_TIME_PAY_RATE
from datetime import datetime
from django.utils import timezone
from cwusers.models import Counselor
from cwcounseling.models import CounselorTimeCard, CounselorTimeEntry


class CounselorTimeCardManagerException(Exception):
    pass


class CounselorTimeCardManager:
    counselor_time_card: CounselorTimeCard = None

    def __init__(self, counselor_time_card):
        self.counselor_time_card = counselor_time_card

    @staticmethod
    def create(counselor: Counselor, start: datetime, end: datetime) -> CounselorTimeCard:
        """ Create a new time card. Will automatically include all CounselorTimeEntry objects that fall within time span
            of time card but AREN'T already on another time card. Returns created time card
        """
        if start >= end:
            raise CounselorTimeCardManagerException("Invalid start/end for time card")
        if not counselor.part_time:
            raise CounselorTimeCardManagerException("Can only create time card for part time counselor")

        counselor_time_entries = CounselorTimeEntry.objects.filter(
            date__gte=start, date__lte=end, counselor_time_card=None, counselor=counselor, hours__gte=0
        )

        time_card = CounselorTimeCard.objects.create(
            counselor=counselor, start=start, end=end, hourly_rate=counselor.hourly_rate,
        )
        counselor_time_entries.filter(category__in=ADMIN_CATEGORIES).update(pay_rate=ADMIN_TIME_PAY_RATE)
        counselor_time_entries.update(counselor_time_card=time_card)
        manager = CounselorTimeCardManager(time_card)
        # TODO: Create notification for counselor
        return manager.set_total()

    def set_total(self) -> CounselorTimeCard:
        """ Re-calculate total.
            We use the following hierarchy to determine pay rate:
            1. Pay rate on time entry
            2. Pay rate on time entry's student
            3. Pay rate on time card
        """
        total = 0
        for entry in self.counselor_time_card.counselor_time_entries.all():
            pay_rate = self.counselor_time_card.hourly_rate
            if entry.pay_rate:
                pay_rate = entry.pay_rate
            elif entry.student and entry.student.counselor_pay_rate:
                pay_rate = entry.student.counselor_pay_rate

            total += entry.hours * pay_rate
        self.counselor_time_card.total = total
        self.counselor_time_card.save()
        return self.counselor_time_card

    def approve_as_counselor(self, note: str = None) -> CounselorTimeCard:
        """ Approve this time card as counselor
        """
        if self.counselor_time_card.counselor_approval_time:
            raise CounselorTimeCardManagerException("Time card already approved as counselor")
        self.counselor_time_card.counselor_approval_time = timezone.now()
        if note:
            self.counselor_time_card.counselor_note = note
        self.counselor_time_card.save()
        return self.counselor_time_card

    def approve_as_admin(self, note: str = None) -> CounselorTimeCard:
        """ Approve time card as admin.
            If not already approved as counselor, then we also approve as counselor
        """
        if self.counselor_time_card.admin_approval_time:
            raise CounselorTimeCardManagerException("Time card already approved as admin")
        if not self.counselor_time_card.counselor_approval_time:
            self.counselor_time_card = self.approve_as_counselor()
        self.counselor_time_card.admin_approval_time = timezone.now()
        if note:
            self.counselor_time_card.admin_note = note
        self.counselor_time_card.save()
        return self.counselor_time_card
