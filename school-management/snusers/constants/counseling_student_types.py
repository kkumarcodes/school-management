OPTIMAL = "opt"
CAP12 = "cap12"
CAP8 = "cap8"
PAYGO = "paygo"
ALL_INCLUSIVE_12 = "ai12"
ALL_INCLUSIVE_8 = "ai8"
NOT_TOO_LATE = "ntl"
FOUNDATIONS = "f"
ESSAY = "e"
PAYGO_ESSAY = "pe"

TYPES_2021 = {
    "Comprehensive Admission Counseling 8": "Comprehensive Admission Counseling 8",
    "Comprehensive Admission Counseling 12": "Comprehensive Admission Counseling 12",
    "Upgrade to CAC 12": "Upgrade to CAC 12",
    "Premier Admissions Counseling ": "Premier Admissions Counseling ",
    "Upgrade to Premier": "Upgrade to Premier",
    "International PAYGO": "International PAYGO",
    "International Comprehensive Admissions Counseling": "International Comprehensive Admissions Counseling",
    "International Premier Admissions Counseling": "International Premier Admissions Counseling",
    "Wiser Summer Planning": "Wiser Summer Planning",
}

COUNSELING_PRODUCT_IDS = [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    111,
    121,
    122,
    123,
]

COUNSELING_STUDENT_TYPES = (
    ("", "None"),
    (OPTIMAL, "Optimal"),
    (CAP12, "CAP 12"),
    (CAP8, "CAP 8"),
    (PAYGO, "Paygo"),
    (ESSAY, "Essay"),
    (PAYGO_ESSAY, "Paygo + Essay"),
    (ALL_INCLUSIVE_12, "All Inclusive 12"),
    (ALL_INCLUSIVE_8, "All Inclusive 8"),
    (NOT_TOO_LATE, "Not Too Late"),
    (FOUNDATIONS, "Foundations"),
) + tuple(TYPES_2021.items())
