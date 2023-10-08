# Schoolnet calls their semesters One (fall), Two (Spring) and Summer
# Events (notably, CounselorMeetings) can take place between semesters as well. Creating a kind of medium-rare situation
ONE = 1
ONE_TWO = 1.5
TWO = 2
TWO_SUMMER = 2.5
SUMMER = 3
SUMMER_ONE = 3.5

CHOICES = (
    (ONE, ONE),
    (ONE_TWO, ONE_TWO),
    (TWO, TWO),
    (TWO_SUMMER, TWO_SUMMER),
    (SUMMER, SUMMER),
    (SUMMER_ONE, SUMMER_ONE),
)

# The fall semester (2) starts in september
FALL_SEMESTER_START_MONTH = 9

# Springs ends in May (inclusive).
SPRING_END_MONTH = 5
