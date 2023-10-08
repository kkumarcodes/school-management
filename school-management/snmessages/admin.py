from django.contrib import admin
from .models import SNPhoneNumber, Conversation, ConversationParticipant

admin.site.register(SNPhoneNumber)
admin.site.register(Conversation)
admin.site.register(ConversationParticipant)