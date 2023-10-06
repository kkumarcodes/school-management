""" Update TaskTemplate to have roadmap """
for tt in TaskTemplate.objects.all():
    roadmaps = Roadmap.objects.filter(
        Q(counselor_meeting_templates__agenda_item_templates__post_meeting_task_templates=tt)
        | Q(counselor_meeting_templates__agenda_item_templates__pre_meeting_task_templates=tt)
    ).distinct()
    if roadmaps.count() == 1:
        tt.roadmap = roadmaps.first()
        tt.save()
        print(tt.roadmap)


""" Create Task with student college questionnaire """

description = """
<p>College search questions:</p>
<p>These questions are meant to guide the conversation about the college search, with the goal of building an initial college list together with the student in this meeting. Feel free to jump around between questions, and find which ones work for each kid.</p>
<ul>
<li>What surprised you about the two videos you watched (overview of colleges/what do I want out of a college)? What did you learn that you didn’t know before?</li>
<li>What priorities did you start to think about as you watched them?</li>
<li>Are there any particular colleges you already find interesting, or colleges that you would like to learn more about?  Which ones? Why have those ones stood out to you?</li>
<li>Are there any particular schools that your family wants you to apply to? Which ones?</li>
<li>How comfortable have you been with change in your life so far (changing schools, being new, having to find new friends, jumping into new experiences in general)?</li>
<li>How would you describe your friends, or the people you tend to feel most yourself around?</li>
<li>What sort of activities do you like to do for fun, say on your ideal Saturday?</li>
<li>Which of these events is something you’d most want to participate in or have access to in college (pick any that stand out to you!): live music concerts, a big game, political speakers, theatre performances, political demonstrations or protests, outdoor sports (hiking, skiing, etc), going to a professional sports game, going to a local coffee shop or restaurant off-campus, walking around a big city</li>
<li>Say you’re in the dining hall at your school – what conversations do you want to hear? Discussions from class, politics, the big game, a mix of all that?</li>
<li>What do you want to avoid repeating from your high school experience?</li>
<li>Are there any majors or topics you want to be able to explore in college?</li>
<li>Are there any areas of the country where you’d like to focus your search (or avoid)?</li>
<li>Have your parents talked about your college budget, and if aid (scholarships, in-state tuition) will be a guiding part of your search?</li>
</ul>
"""

(tt, _) = TaskTemplate.objects.get_or_create(roadmap=None, title="College Search Questions")
tt.description = description
tt.form = None
tt.require_content_submission = True
tt.save()
print(tt)
