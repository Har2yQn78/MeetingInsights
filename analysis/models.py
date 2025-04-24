from django.db import models
from django.utils.translation import gettext_lazy as _
from transcripts.models import Transcript

class AnalysisResult(models.Model):
    transcript = models.OneToOneField(Transcript,on_delete=models.CASCADE, related_name='analysis',primary_key=True)
    summary = models.TextField(blank=True, null=True)
    key_points = models.JSONField(default=list,blank=True,null=True,
                                  help_text="A list of key points extracted from the transcript,"
                                            " e.g., ['Point A', 'Point B'].")
    task = models.CharField(max_length=255, default="", blank=True)
    responsible = models.CharField(max_length=255, blank=True, default="")
    deadline = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Analysis Result"
        verbose_name_plural = "Analysis Results"

    def __str__(self):
        meeting_title = self.transcript.meeting.title
        title_short = (meeting_title[:30] + '...') if len(meeting_title) > 30 else meeting_title
        return f"Analysis for Transcript of '{title_short}'"