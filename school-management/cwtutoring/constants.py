NOTIFY_ADMIN_INDIVIDUAL_HOUR_THRESHOLD = 2
NOTIFY_ADMIN_GROUP_HOUR_THRESHOLD = 2

# NOTE: There are frontend setting analogs for recurring availability in date-utils.ts

# Start and end dates for three recurring availability schedules
# Everything before this month is spring
RECURRING_AVAILABILITY_SUMMER_START_MONTH = 6
# Everything after summer start and before fall start is summer
# Everything after this month is fall
RECURRING_AVAILABILITY_FALL_START_MONTH = 9

# Amount we charge for late cancel
LATE_CANCEL_CHARGE = 70

# Values for "Category" on TutorTimeCardLineItem
TIME_CARD_CATEGORY_CHECK_IN = "Check-In"
TIME_CARD_CATEGORY_SESSION_NOTES_ADMIN = "Session Notes/Administrative"
TIME_CARD_CATEGORY_TRAINING_PD = "Training/Professional Development"
TIME_CARD_CATEGORY_TUTORING = "Tutoring"  # Cal also be None
TIME_CARD_CATEGORY_DIAG_REPORT = "Diag Report"
TIME_CARD_CATEGORY_EVAL_CONSULTS = "Evals/Consults"
