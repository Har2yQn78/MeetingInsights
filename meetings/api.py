from typing import List, Optional
from datetime import datetime
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth
from .models import Meeting
from .schemas import MeetingSchemaIn, MeetingSchemaOut, MeetingSchemaUpdate, ErrorDetail

router = Router(tags=["meetings"])

@router.post("/", response={201: MeetingSchemaOut, 400: ErrorDetail}, auth=JWTAuth(), summary="Create Meeting",
             description="""
             Creates a new meeting record in the system.

             **Details:**
             - Requires authentication via JWT.
             - Accepts a JSON payload conforming to the `MeetingSchemaIn`.
             - The `title` field is mandatory.
             - If `meeting_date` is not provided in the payload, it defaults to the current server time (UTC) upon creation.
             - `participants` (list) and `metadata` (dict) are optional fields for storing additional meeting information.

             **On Success:** Returns `201 Created` with the full details of the newly created meeting (conforming to `MeetingSchemaOut`).
             **On Failure:** Returns `400 Bad Request` if input validation fails or another creation error occurs.
             """
             )
def create_meeting(request, data: MeetingSchemaIn):
    try:
        meeting = Meeting.objects.create(title=data.title, meeting_date=data.meeting_date or datetime.now(),
                                         participants=data.participants, metadata=data.metadata if hasattr(data, 'metadata') else None)
        return 201, meeting
    except Exception as e:
        return 400, {"detail": str(e)}


@router.get("/", response=List[MeetingSchemaOut], auth=JWTAuth(), summary="List Meetings",
            description="""
            Retrieves a list of meeting records, with options for filtering and pagination.

            **Details:**
            - Requires authentication via JWT.
            - Returns a list of meetings conforming to the `MeetingSchemaOut`.
            - Meetings are ordered by creation date (most recent first) by default.

            **Filtering (Query Parameters):**
            - `title`: Filter meetings by title using a case-insensitive containment search (e.g., `?title=Weekly`).
            - `date_from`: Filter meetings occurring on or after this date/time (ISO 8601 format, e.g., `?date_from=2024-01-01T00:00:00Z`).
            - `date_to`: Filter meetings occurring on or before this date/time (ISO 8601 format, e.g., `?date_to=2024-01-31T23:59:59Z`).

            **Pagination (Query Parameters):**
            - `offset`: The number of items to skip from the beginning of the result set (default: 0).
            - `limit`: The maximum number of items to return in a single response (default: 100).
            """
            )
def list_meetings(request, title: Optional[str] = None, date_from: Optional[datetime] = None,
                  date_to: Optional[datetime] = None, offset: int = 0, limit: int = 100):
    queryset = Meeting.objects.all()

    if title:
        queryset = queryset.filter(title__icontains=title)
    if date_from:
        queryset = queryset.filter(meeting_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(meeting_date__lte=date_to)

    return queryset.order_by('-created_at')[offset:offset + limit]


@router.get("/{meeting_id}/", response={200: MeetingSchemaOut, 404: ErrorDetail}, auth=JWTAuth(), summary="Get Meeting by ID",
            description="""
            Retrieves the details of a specific meeting by its unique ID.

            **Details:**
            - Requires authentication via JWT.
            - Uses the `meeting_id` provided in the URL path.

            **On Success:** Returns `200 OK` with the meeting details conforming to `MeetingSchemaOut`.
            **On Failure:** Returns `404 Not Found` if no meeting exists with the specified `meeting_id`.
            """
            )
def get_meeting(request, meeting_id: int):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
        return 200, meeting
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}


@router.put("/{meeting_id}/", response={200: MeetingSchemaOut, 404: ErrorDetail, 400: ErrorDetail}, auth=JWTAuth(),
            summary="Update Meeting",
            description="""
            Updates an existing meeting record partially.

            **Important Note:** While using the HTTP PUT method, this endpoint performs a *partial* update (like PATCH).
             Only the fields provided in the request payload will be updated. Fields omitted from the payload will retain their current values.

            **Details:**
            - Requires authentication via JWT.
            - Uses the `meeting_id` provided in the URL path to identify the meeting.
            - Accepts a JSON payload conforming to `MeetingSchemaUpdate`, where all fields are optional.

            **On Success:** Returns `200 OK` with the updated meeting details conforming to `MeetingSchemaOut`.
            **On Failure:**
                - Returns `404 Not Found` if no meeting exists with the specified `meeting_id`.
                - Returns `400 Bad Request` if the input data is invalid or another error occurs during the update.
            """
            )
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
               description="""
               Deletes a specific meeting record identified by its unique ID.

               **Warning:** This operation is irreversible and will also delete associated transcripts and analysis results due to database cascade settings.

               **Details:**
               - Requires authentication via JWT.
               - Uses the `meeting_id` provided in the URL path.

               **On Success:** Returns `204 No Content` indicating successful deletion.
               **On Failure:** Returns `404 Not Found` if no meeting exists with the specified `meeting_id`.
               """
               )
def delete_meeting(request, meeting_id: int):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
        meeting.delete()
        return 204, None
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}