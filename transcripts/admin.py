from django.contrib import admin

# Register your models here.

from .models import Transcript
from analysis.models import AnalysisResult
class AnalysisResultInline(admin.StackedInline):
    model = AnalysisResult
    readonly_fields = ('created_at', 'updated_at')
    can_delete = False
    verbose_name_plural = "Analysis Result"
    fk_name = 'transcript'
    extra = 0
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
        ('Processing Details', {'fields': ('processing_status', 'processing_error', 'async_task_id'), 'classes': ('collapse',)}),
        ('Content', {'fields': ('raw_text',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    inlines = [AnalysisResultInline]