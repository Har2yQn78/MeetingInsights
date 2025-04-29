from django.contrib import admin

# Register your models here.

from .models import Meeting, Transcript

@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ('title', 'meeting_date', 'created_at', 'updated_at')
    list_filter = ('meeting_date', 'created_at')
    search_fields = ('title',)
    date_hierarchy = 'meeting_date'
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = ((None, {'fields': ('title', 'meeting_date', 'participants', 'metadata')}),('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),)

@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'meeting',
        'processing_status',
        'original_file',
        'created_at',
        'updated_at',
    )

    list_filter = (
        'processing_status',
        'meeting',
        'created_at',
    )

    search_fields = (
        'title',
        'meeting__title',
        'raw_text',
        'async_task_id',
    )

    autocomplete_fields = ['meeting']
    readonly_fields = (
        'created_at',
        'updated_at',
        'processing_error',
        'async_task_id',
    )

    fieldsets = (
        (None, {'fields': ('meeting', 'title', 'original_file')}),
        ('Processing Details', {
            'fields': ('processing_status', 'processing_error', 'async_task_id'),
            'classes': ('collapse',),
            'description': "Details about the asynchronous transcription process."}),
        ('Content', {'fields': ('raw_text',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'),'classes': ('collapse',),}),)
