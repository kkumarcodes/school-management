from django.contrib import admin
from .models import CWPhoneNumber, Conversation, ConversationParticipant

admin.site.register(CWPhoneNumber)
admin.site.register(Conversation)
admin.site.register(ConversationParticipant)