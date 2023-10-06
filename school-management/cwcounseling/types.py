from typing import List, Optional
from typing_extensions import TypedDict
from cwcounseling.models import CounselorMeetingTemplate


class RoadmapMeeting(TypedDict):
    """ Data structure representing a meeting to create when applying a roadmap
        Includes agenda item template PKS for agenda items to create
    """

    counselor_meeting_template: CounselorMeetingTemplate  # Will create CounselorMeeting from this template
    meeting_title: Optional[str]  # Custom title for meeting
    agenda_item_templates: List[int]  # Agenda items will be created for meeting from
    custom_agenda_items: List[str]  # Custom agenda items to create (not from AgendaItemTemplate)
