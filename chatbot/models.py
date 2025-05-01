from django.db import models
import os

# Create your models here.

from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField
from transcripts.models import Transcript
from django.conf import settings
from decouple import config, AutoConfig

config_search_path = settings.BASE_DIR if hasattr(settings, 'BASE_DIR') else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config = AutoConfig(search_path=config_search_path)

MISTRAL_EMBEDDING_DIM = config("MISTRAL_EMBEDDING_DIM", default=1024, cast=int)


class TextChunk(models.Model):
    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name='chunks')
    text = models.TextField(blank=False, null=False)
    embedding = VectorField(dimensions=MISTRAL_EMBEDDING_DIM, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['transcript', 'created_at']
        indexes = [
            models.Index(fields=['transcript']),
        ]
        verbose_name = _("Text Chunk")
        verbose_name_plural = _("Text Chunks")

    def __str__(self):
        return f"Chunk for Transcript {self.transcript_id} ({len(self.text)} chars)"
