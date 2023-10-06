from django.contrib import admin
from .models import (
    CounselorMeetingTemplate,
    CounselorMeeting,
    Roadmap,
    CounselingHoursGrant,
    CounselorTimeEntry,
    CounselorTimeCard,
)

admin.site.register(CounselorMeetingTemplate)
admin.site.register(CounselorMeeting)
admin.site.register(Roadmap)
admin.site.register(CounselorTimeCard)
admin.site.register(CounselingHoursGrant)
admin.site.register(CounselorTimeEntry)
