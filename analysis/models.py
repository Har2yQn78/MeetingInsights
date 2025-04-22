from django.db import models
from django.utils.translation import gettext_lazy as _
from transcripts.models import Transcript

class AnalysisResult(models.Model):
    transcript = models.OneToOneField(Transcript,on_delete=models.CASCADE, related_name='analysis',primary_key=True)
    summary = models.TextField(blank=True, null=True)
    key_points = models.JSONField(default=list,blank=True,null=True,
                                  help_text="A list of key points extracted from the transcript,"
                                            " e.g., ['Point A', 'Point B'].")
    action_items = models.JSONField(default=list,blank=True,null=True,
                                    help_text=_("List of action items, e.g., [{'task': 'Send meeting notes',"
                                                " 'responsible': 'Alice', 'deadline': 'YYYY-MM-DD'}]")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at'] # Show newest results first
        verbose_name = "Analysis Result"
        verbose_name_plural = "Analysis Results"

    def __str__(self):
        meeting_title = self.transcript.meeting.title
        title_short = (meeting_title[:30] + '...') if len(meeting_title) > 30 else meeting_title
        return f"Analysis for Transcript of '{title_short}'"