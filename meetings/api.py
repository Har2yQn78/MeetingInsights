from typing import List, Optional
from datetime import datetime
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth
from .models import Meeting
from .schemas import MeetingSchemaIn, MeetingSchemaOut, MeetingSchemaUpdate, ErrorDetail

router = Router(tags=["meetings"])

@router.post("/", response={201: MeetingSchemaOut, 400: ErrorDetail}, auth=JWTAuth(), summary="create meeting",
             description="Creates a new meeting record with the provided title, date, participants, and metadata.")
def create_meeting(request, data: MeetingSchemaIn):
    try:
        meeting = Meeting.objects.create(
            title=data.title,
            meeting_date=data.meeting_date or datetime.now(),
            participants=data.participants,
            metadata=data.metadata if hasattr(data, 'metadata') else None
        )
        return 201, meeting
    except Exception as e:
        return 400, {"detail": str(e)}


@router.get("/", response=List[MeetingSchemaOut], auth=JWTAuth(), summary="list meetings",
            description="List all meetings.")
def list_meetings(
        request,
        title: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 100
):
    queryset = Meeting.objects.all()

    if title:
        queryset = queryset.filter(title__icontains=title)
    if date_from:
        queryset = queryset.filter(meeting_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(meeting_date__lte=date_to)

    return queryset.order_by('-created_at')[offset:offset + limit]


@router.get("/{meeting_id}/", response={200: MeetingSchemaOut, 404: ErrorDetail}, auth=JWTAuth(), summary="Get Meeting by ID",
            description="Retrieves the details of a specific meeting by its unique ID.")
def get_meeting(request, meeting_id: int):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
        return 200, meeting
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}


@router.put("/{meeting_id}/", response={200: MeetingSchemaOut, 404: ErrorDetail, 400: ErrorDetail}, auth=JWTAuth(),
            summary="Update Meeting", description="Updates an existing meeting record partially. Only provided fields will be updated.")
def update_meeting(request, meeting_id: int, data: MeetingSchemaUpdate):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)

        if data.title is not None:
            meeting.title = data.title
        if data.meeting_date is not None:
            meeting.meeting_date = data.meeting_date
        if data.participants is not None:
            meeting.participants = data.participants
        if hasattr(data, 'metadata') and data.metadata is not None:
            meeting.metadata = data.metadata

        meeting.save()
        return 200, meeting
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}
    except Exception as e:
        return 400, {"detail": str(e)}


@router.delete("/{meeting_id}/", response={204: None, 404: ErrorDetail}, auth=JWTAuth(), summary="Delete Meeting",
               description="Deletes a specific meeting record by its ID")
def delete_meeting(request, meeting_id: int):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
        meeting.delete()
        return 204, None
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}