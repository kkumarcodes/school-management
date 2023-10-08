# SNCounseling
This app contains models and business logic specific to the Schoolnet Counseling platform (CAP) within
UMS. Significant concepts include:
- Counseling Tasks (mostly implemented in `sntasks`)
- Counseling Meetings with agenda items
- Roadmaps, which represent a set of meetings, agenda items, and tasks for a student
- Counseling student profiles including: Coursework, Activities, Notes, and FileUploads


## Roadmaps
A Roadmap is a set of meetings (with agenda items) and tasks that are created for a student when they start working
with Schoolnet. A Roadmap is meant to represent all of the work and meetings a student will engage in throughout their entire time with Schoolnet. Counselors can, of course, create custom meetings and tasks for students that are not apart of a Roadmap. But standardizing meetings and tasks through Roadmaps makes it faster for counselors to get students setup in UMS, and provides a more standardized approach to counseling prescribed by Schoolnet.

Technically, a `CounselorMeeting` object represents a single meeting between a `Student` and `Counselor`. A `CounselorMeeting` as zero or more `AgendaItem`s, which are set by the `Counselor`. An `AgendaItem`, in turn, has zero or more pre meeting and post meeting tasks (`pre_meeting_task_templates` and `post_meeting_task_templates` ,respectively).

Crucially, `CounselorMeeting`, `AgendaItem`, and `Task` represent instances of objects that are specific to a particular meeting and student. Schoolnet has defined "templates" for each of these concepts, that allow counselors to copy pre-set details (like titles, related resources, related tasks) when creating a new `CounselorMeeting`, `AgendaItem`, or `Task`. The models representing these templates are - respecitvely - `CounselorMeetingTemplate`, `AgendaItemTemplate` and `TaskTemplate`.

Thus, a `CounselorMeetingTemplate` has zero or more `AgendaItemTemplate`s that represent the typical set of agenda items for the meeting. When a counselor creates a new `CounselorMeeting` from the `CounselorMeetingTemplate`, UMS will default to creating `AgendaItem`s for all of that `CounselorMeetingTemplate`'s `AgendaItemTemplate`'s, but the counselor can customize or filter the actual set of resulting `AgendaItem`s such that their details differ from the related `AgendaItemTemplate`.

Similarly, `AgendaItemTemplate`s have sets of pre and post meeting `TaskTemplates` representing the typical set of tasks that are to be created for a student before and after the meeting that the agenda item was for.

### Roadmap Example
See the [Late Start Senior](https://docs.google.com/spreadsheets/d/1oAshALY44ina1a-FJAJ4wzEIWojj_IwGxCeGoUakZdc/edit#gid=0) roadmap example. This `Roadmap` defines nine `CounselorMeetings`. Each row in this Sheet represents a single `TaskTemplate`-`AgendaItemTemplate` combination. For example, the intake meeting template defines 2 unique agenda items: "Review all questionnaires.." and "Review transcript...". There are 4 `TaskTemplates` that are associated with either of these two agenda items, 3 for the questionnairre agenda item, and 1 for the transcript agenda item. When this roadmap is applied to the student, an intake `CounselorMeeting` would be created from the intake `CounselorMeetingTemplate` associated with this `Roadmap`. That `CounselorMeeting` would have two associated `AgendaItem`s and 4 `Task`s would be created for this student (for this meeting). In practice, a counselor could customize all of this, and choose not to create some agenda items or choose not to create this meeting entirely when applying the roadmap.

### Updating the counselor tracker upon assignign or completing some tasks
There are certain `TaskTemplate`s that update fields on the counselor tracker (these fields are on the `StudentUniversityDecision` object) when tasks associated with the template are assigned or completed.
For example, when `Task`s associated with the "Send Letters of Recommendation" `TaskTemplate` are assigned, schools associated with the task have their "Recommendation" status on the tracker changed to `assigned`. When those tasks are completed, they have their status on the tracker changed to `requested`.
We also 
Here's how it works:
- `TaskTemplate`.`include_school_sud_values` is a dictionary of filter arguments that can be used to filter a student's `StudentUniversityDecision`s for those ass
