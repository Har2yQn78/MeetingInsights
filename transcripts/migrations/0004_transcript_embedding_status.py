# Generated by Django 5.2 on 2025-05-01 14:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transcripts', '0003_transcript_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='transcript',
            name='embedding_status',
            field=models.CharField(choices=[('NONE', 'None'), ('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')], db_index=True, default='NONE', max_length=20),
        ),
    ]
