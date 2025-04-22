from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

# Create your models here.

class Meeting(models.Model):
    title = models.CharField(max_length=255, blank=False, null=False,)
    meeting_date = models.DateTimeField(default=timezone.now, db_index=True)
    participants = models.JSONField(default=list, blank = True, null = True)
    created_at = models.DateTimeField(auto_now_add=True,)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-meeting_date', '-created_at']
        verbose_name = "Meeting"
        verbose_name_plural = "Meetings"

    def __str__(self):
        date_str = self.meeting_date.strftime('%Y-%m-%d %H:%M') if self.meeting_date else 'N/A'
        return f"{self.title} ({date_str})"
