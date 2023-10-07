""" Utility to help with creation and updates of TutorTimeCard (and TutorTimeCardLineItem) objects
"""
from decimal import Decimal
from datetime import datetime, timedelta
from sentry_sdk import configure_scope, capture_exception
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from django.db.models import F, Sum
from sntutoring.models import (
    TutorTimeCard,
    TutorTimeCardLineItem,
    StudentTutoringSession,
    GroupTutoringSession,
)


class TutorTimeCardException(Exception):
    pass


class TutorTimeCardManager:
    tutor = None

    def __init__(self, tutor):
        """ Init with param tutor {Tutor} """
        self.tutor = tutor

    @staticmethod
    def create_many_time_cards(tutors, start, end, include_sessions=True, adjust_to_end_previous_day=True, send=False):
        """ Helper method for making time cards for multiple editors. Note that we'll adapt start/end to exclude
            any timespans already covered by other time cards for a tutor since time cards cannot overlap.
            So resulting time cards may be different across different tutors.
            Time cards cannot be disjoint, so if a tutor has multiple time cards spanning our start-end range, then
            no time card will be created
            Arguments:
                tutors {Tutor[]}
                start, end, include_sessions -- see create_time_card
                adjust_to_end_previous_day {Bool} To account for timezones, time cards are created to run from 6 am
                    to 6am. But we need them to appear as ending at 23:59 the day before the end date (so they
                    run sat - Fri instead of Sat - Sat). If this is True, then after time cards are created we make
                    this adjustment.
                send: Whether or not email notifications should be sent for timecards
            Returns:
                TimeCard[], List of skipped tutor PKs
        """
        skipped = []
        created_time_cards = []
        for tutor in tutors:
            existing_time_cards = TutorTimeCard.objects.filter(tutor=tutor).filter(
                Q(start__gte=start, start__lte=end) | Q(end__gte=start, end__lte=end)
            )
            count = existing_time_cards.count()
            tutor_start = start
            tutor_end = end
            if count > 1:
                skipped.append(tutor.pk)
                continue  # Just skip this tutor if they have multiple timecards that overlap
            elif count == 1:
                existing_time_card = existing_time_cards.first()
                # Skip if existing time card entirely covers current time span, or time card breaks proposed
                # time span in two or overlaps either the start or end of a time card
                if (
                    (existing_time_card.start > tutor_start and existing_time_card.end < tutor_end)
                    or (existing_time_card.start <= tutor_start and existing_time_card.end >= tutor_end)
                    or (existing_time_card.start < tutor_start and tutor_start < existing_time_card.end)
                    or (existing_time_card.start < tutor_end and tutor_end < existing_time_card.end)
                ):
                    skipped.append(tutor.pk)
                    raise Exception("Cannot create overlapping timecards")
                if existing_time_card.start > tutor_start:
                    # Existing time card starts after our current start. We need to end at its start
                    tutor_end = existing_time_card.start
                elif existing_time_card.end < tutor_end:
                    # Existing time card ends before ours. We start at its end
                    tutor_start = existing_time_card.end

            # Now we are finally ready to create our time card
            try:
                mgr = TutorTimeCardManager(tutor)
                created_time_cards.append(
                    mgr.create_time_card(tutor_start, tutor_end, include_sessions=include_sessions)
                )
            except TutorTimeCardException as e:
                if not (settings.TESTING or settings.DEBUG):
                    with configure_scope() as scope:
                        scope.set_context(
                            "create_tutor_timecard", {"tutor": tutor.pk, "start": str(start), "end": str(end)},
                        )
                        capture_exception(e)
                skipped.append(tutor.pk)
            if adjust_to_end_previous_day:
                previous_day = end - timedelta(days=1)
                for time_card in created_time_cards:
                    time_card.end = datetime(previous_day.year, previous_day.month, previous_day.day, 23, 59)
                    time_card.save()
        return (created_time_cards, skipped)

    def calculate_total(self, time_card, refresh_pay_rate=False):
        """ Calculate the total to be paid to tutor, based on sessions and line items
            Arguments:
                time_card {TimeCard}
                refresh_pay_rate {Boolean} If True then we'll get updated pay rate from tutor obj
            Return:
                {TimeCard} with updated total field
        """
        if refresh_pay_rate:
            time_card.hourly_rate = time_card.tutor.hourly_rate
        # Calculate total for line items as they have their own hourly rates
        line_items_with_hourly_rate = time_card.line_items.exclude(hourly_rate=None)
        line_items_without_hourly_rate = time_card.line_items.filter(hourly_rate=None)

        line_item_total = line_items_with_hourly_rate.annotate(total=F("hours") * F("hourly_rate")).aggregate(
            t=Sum("total")
        )["t"] or Decimal(0)

        tutoring_sessions_total = (
            line_items_without_hourly_rate.aggregate(hours=Sum("hours"))["hours"] or 0
        ) * time_card.hourly_rate

        time_card.total = Decimal(line_item_total) + Decimal(tutoring_sessions_total)
        time_card.save()
        return time_card

    def create_time_card(self, start, end, include_sessions=True):
        """ Create a new time card for tutor.
            Arguments:
                start {datetime}: Beginning (start) date for timecard. Should be 00:00 on the first day timecard covers
                end {datetime}: Last (end) date for timecard Should be 24:00 on the last day time card covers
                    (i.e. beginning of next day)
                include_sessions: Whether or not this new time card should automatically have
                    line items created for self.tutor's sessions during time period covered by time card
            Returns: TutorTimeCard
        """
        if not self.confirm_time_span_valid(start, end):
            raise TutorTimeCardException("Invalid time span for new time card")
        time_card = TutorTimeCard.objects.create(
            tutor=self.tutor, start=start, end=end, hourly_rate=self.tutor.hourly_rate
        )
        if include_sessions:
            # Create line items for all sessions that fall in our date range
            individual_sessions = StudentTutoringSession.objects.filter(
                individual_session_tutor=self.tutor, start__gte=start, start__lt=end, is_tentative=False
            ).filter(Q(set_cancelled=False) | Q(late_cancel=True),)
            for session in individual_sessions:
                TutorTimeCardLineItem.objects.create(
                    title=f"Individual tutoring session with {session.student.name}",
                    date=session.start,
                    individual_tutoring_session=session,
                    hours=Decimal(session.duration_minutes / 60.0),
                    time_card=time_card,
                )

            group_sessions = (
                GroupTutoringSession.objects.filter(Q(primary_tutor=self.tutor) | Q(support_tutors=self.tutor))
                .filter(cancelled=False, start__gte=start, start__lt=end)
                .distinct()
            )
            for session in group_sessions:
                # If session is set to 0 minutes, then it's a diagnostic that we aren't charging families for
                # but still need to pay tutors for (so we use the calculated duration instead of set duration
                # for pay)
                # see GroupTutoringSession.pay_tutor_duration
                TutorTimeCardLineItem.objects.create(
                    title=f"Group session: {session.title}",
                    date=session.start,
                    group_tutoring_session=session,
                    hours=Decimal(session.pay_tutor_duration / 60.0),
                    time_card=time_card,
                )
        return self.calculate_total(time_card, refresh_pay_rate=True)

    def confirm_time_span_valid(self, start, end):
        """ Confirm that time span from start to end can be used to create a new time card (i.e. does
            not overlap with existing time card)
            Arguments:
                start {datetime}
                end {datetime}
            Returns bool
        """
        # Check to see if proposed span would overlap with any existing timecard
        return not TutorTimeCard.objects.filter(tutor=self.tutor, start__lt=end, end__gt=start).exists()

    def tutor_approve(self, timecard):
        """ self.tutor is approving one of their own time cards. Update TutorTimeCard object,
            send necessary notifications.
            Arguments:
                timecard {TutorTimeCard}
            Returns: Updated TutorTimeCard
        """
        if timecard.tutor != self.tutor:
            raise TutorTimeCardException("Tutor can't approve another tutor's timecard")
        timecard.tutor_approval_time = timezone.now()
        timecard.save()
        return timecard

    def admin_approve(self, timecard, admin):
        """ An admin approves one of our tutor's time cards. Update TutorTimeCard object,
            send necessary notifications.
            Arguments:
                timecard {TutorTimeCard}
                admin {Administrator}
            Returns: Updated TutorTimeCard
        """
        timecard.admin_approver = admin
        timecard.admin_approval_time = timezone.now()
        timecard.save()
        return timecard
