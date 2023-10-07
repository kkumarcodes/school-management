from django.contrib import admin
from .models import (
    Student,
    Parent,
    Tutor,
    Administrator,
    Counselor,
    StudentHighSchoolCourse,
)

admin.site.register(Student)
admin.site.register(Parent)
admin.site.register(Tutor)
admin.site.register(Counselor)
admin.site.register(Administrator)
admin.site.register(StudentHighSchoolCourse)
