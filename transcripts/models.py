from django.db import models
from django.utils.translation import gettext_lazy as _
from meetings.models import Meeting
import os

# Create your models here.

class Transcript(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')

    class EmbeddingStatus(models.TextChoices):
        NONE = 'NONE', _('None')
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')

    embedding_status = models.CharField(max_length=20, choices=EmbeddingStatus.choices,
                                        default=EmbeddingStatus.NONE, db_index=True)
    meeting = models.ForeignKey(Meeting,on_delete=models.CASCADE,related_name='transcripts',)
    title = models.CharField(max_length=255, blank=True, null=True)
    raw_text = models.TextField(blank=True, null=True)
    original_file = models.FileField(upload_to='transcripts/%Y/%m/%d/',blank=True,null=True)
    processing_status = models.CharField(max_length=20,choices=ProcessingStatus.choices,
                                         default=ProcessingStatus.PENDING,db_index=True,)
    processing_error = models.TextField(blank=True,null=True,)
    async_task_id = models.CharField(max_length=255,blank=True,null=True,db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Transcript"
        verbose_name_plural = "Transcripts"


    def __str__(self):
        meeting_title = (self.meeting.title[:30] + '...') if len(self.meeting.title) > 30 else self.meeting.title
        return f"Transcript for '{meeting_title}' (Status: {self.get_processing_status_display()})"
