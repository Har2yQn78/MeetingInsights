from django.db import models
from django.utils.translation import gettext_lazy as _
from meetings.models import Meeting

# Create your models here.

class Transcript(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name='transcripts', # Allows accessing transcripts from a meeting object (meeting.transcripts.all())
        help_text="The meeting this transcript belongs to."
    )

    # --- Transcript Content ---
    # Storing raw text directly. If handling file uploads, the view/service
    # layer will be responsible for extracting text before saving here.
    raw_text = models.TextField(
        blank=False,
        null=False,
        help_text="The raw text content of the meeting transcript."
    )
    # Optional: If you want to store the original file as well
    # original_file = models.FileField(
    #     upload_to='transcripts/%Y/%m/%d/', # Example upload path
    #     blank=True,
    #     null=True,
    #     help_text="Optional: The original uploaded transcript file."
    # )

    # --- Processing Information ---
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True, # Often queried by status
        help_text="The current status of the AI processing workflow."
    )
    processing_error = models.TextField(
        blank=True,
        null=True,
        help_text="Stores any error message if processing failed."
    )
    # Optional: Store the async task ID (e.g., from Celery)
    # async_task_id = models.CharField(
    #     max_length=255,
    #     blank=True,
    #     null=True,
    #     db_index=True,
    #     help_text="The ID of the asynchronous task processing this transcript."
    # )

    # --- Timestamps ---
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the transcript record was created."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the transcript record was last updated."
    )

    class Meta:
        ordering = ['-created_at'] # Show newest transcripts first by default
        verbose_name = "Transcript"
        verbose_name_plural = "Transcripts"
        # Ensures that a meeting can only have one transcript directly linked this way
        # If you might want multiple transcripts per meeting (e.g., different versions), remove this constraint.
        # constraints = [
        #     models.UniqueConstraint(fields=['meeting'], name='unique_transcript_per_meeting')
        # ]


    def __str__(self):
        """
        Provides a human-readable representation.
        """
        # Limit title length for display
        meeting_title = (self.meeting.title[:30] + '...') if len(self.meeting.title) > 30 else self.meeting.title
        return f"Transcript for '{meeting_title}' (Status: {self.get_processing_status_display()})"
