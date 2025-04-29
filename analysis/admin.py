from django.contrib import admin

# Register your models here.

from .models import AnalysisResult
from transcripts.models import Transcript
from meetings.models import Meeting


@admin.register(AnalysisResult)
class AnalysisResultAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'task',
        'responsible',
        'deadline',
        'updated_at',
    )
    list_filter = (
        'deadline',
        'responsible',
        'transcript__meeting',
    )
    search_fields = (
        'summary__icontains',
        'key_points__icontains',
        'task__icontains',
        'responsible__icontains',
        'transcript__title__icontains',
        'transcript__meeting__title__icontains',
    )
    autocomplete_fields = ['transcript']
    readonly_fields = (
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (None, {'fields': ('transcript',)}),
        ('Analysis Content', {'fields': ('summary', 'key_points')}),
        ('Action Items', {'fields': ('task', 'responsible', 'deadline')}),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),}),)

class AnalysisResultInline(admin.StackedInline):
    model = AnalysisResult
    readonly_fields = ('created_at', 'updated_at')
    can_delete = False
    verbose_name_plural = "Analysis Result"
    fk_name = 'transcript'