""" This module contains the mapping of app requirements as they exist in the Airtable CW uses to collect
    app requirements, to the values that we need to set on StudentUniversityDecision objects when they are created
    Structure is like this:
    {
        University field name: {
            sud_field_name: string,
            values: {
                key value pairs where keys are options for the uni field name, and vals are what we set
                sud_field_name to
            }
        }
    }
"""
from typing import Optional
from cwuniversities.constants.application_tracker_status import *

NOT_OFFERED = "Not Offered"
INTERVIEW_REQUIRED = "Required"
INTERVIEW_OPTIONAL = "Optional"
INTERVIEW_REQUIREMENT_OPTIONS = (
    ("Required", INTERVIEW_REQUIRED),
    ("Optional", INTERVIEW_OPTIONAL),
    ("Not Offered", NOT_OFFERED),
)

APP_REQUIREMENTS_MAPPING = {
    "transcript_requirements": {
        "sud_field_name": "transcript_status",
        "values": {"Official Required": REQUIRED, "Unofficial Allowed": OPTIONAL, "Self-Reported": NOT_APPLICABLE},
    },
    "testing_requirements": {
        "sud_field_name": "test_scores_status",
        "values": {
            "SAT/ACT Required": REQUIRED,
            "Test Flexible": REQUIRED,
            "Test Free": NOT_APPLICABLE,
            "Test Optional": OPTIONAL,
            "Test Optional with Exception": OPTIONAL,
        },
    },
}
