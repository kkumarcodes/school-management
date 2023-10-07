""" This module contains a function that generates a PDF of tutoring session notes
    Placed in this module to avoid circular imports
"""
import pdfkit

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.conf import settings

TEMPLATE = "sntutoring/tutoring_session_notes.html"


def generate_pdf(student_tutoring_session):
    """ Generate a PDF from our notes and return it as a ContentFile (PDF)
            Arguments:
                student_tutoring_session {StudentTutoringSession} session to generate notes for.
        """
    if (
        not student_tutoring_session.tutoring_session_notes
        or not student_tutoring_session.tutoring_session_notes.notes
    ):
        raise ValueError("Cannot generate PDF without notes")
    content = render_to_string(
        TEMPLATE,
        context={"session": student_tutoring_session, "SITE_URL": settings.SITE_URL,},
    )
    return ContentFile(
        pdfkit.from_string(content, False,),
        name=f"{student_tutoring_session} notes.pdf",
    )
