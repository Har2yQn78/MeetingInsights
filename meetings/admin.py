from django.contrib import admin

# Register your models here.

from .models import Meeting

@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ('title', 'meeting_date', 'created_at')
    search_fields = ['title']
    list_filter = ('meeting_date',)
    date_hierarchy = 'meeting_date'
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = ((None, {'fields': ('title', 'meeting_date', 'participants', 'metadata')}),('Timestamps', {'fields': ('created_at', 'updated_at'),'classes': ('collapse',),}),)