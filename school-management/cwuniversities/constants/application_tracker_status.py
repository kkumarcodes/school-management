""" Statuses for counselor application tracker. Pulled from Airtable that CW provided as a template
"""
NOT_APPLICABLE = "n_a"

# APPLICATION
APPLICATION_ON_DECK = "on_deck"
APPLICATION_READY = "ready"
APPLICATION_IN_PROGRESS = "in_progress"
APPLICATION_SUBMITTED = "submitted"
APPLICATION_STATUS_CHOICES = (
    (NOT_APPLICABLE, "N/A"),
    (APPLICATION_IN_PROGRESS, "In Progress"),
    (APPLICATION_READY, "Ready to Submit"),
    (APPLICATION_ON_DECK, "On Deck"),
    (APPLICATION_SUBMITTED, "Submitted"),
)

# Transcripts, Test Scores, and Letter of Rec

NONE = ""
ASSIGNED = "assigned"
IN_PROGRESS = "in_progress"
REQUESTED = "requested"
RECEIVED = "received"
REQUIRED = "required"
OPTIONAL = "optional"
NOT_REQUIRED = "not_required"
STATUS_CHOICES = (
    (NONE, "None"),
    (NOT_APPLICABLE, "N/A"),
    (REQUIRED, "required"),
    (OPTIONAL, "optional"),
    (ASSIGNED, "Assigned to Order"),
    (IN_PROGRESS, "In Progress"),  # DEPRECATED - not supported on frontend
    (REQUESTED, "Requested/Ordered"),
    (RECEIVED, "Received"),
)
