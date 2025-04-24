import streamlit as st
import requests
import json
from datetime import datetime, timedelta

# --- Configuration ---
API_BASE_URL = st.sidebar.text_input("API Base URL", "http://127.0.0.1:8000/api")


# --- Authentication Management ---
def login(username, password):
    """Authenticate user and get JWT token"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/pair",  # Updated to match your API endpoint
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        token_data = response.json()

        # Store tokens and expiry time
        st.session_state.access_token = token_data["access"]
        st.session_state.refresh_token = token_data["refresh"]
        # Calculate expiry time (typically 5 minutes for access token)
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4)
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                st.error(e.response.json().get("detail", "Unknown error"))
            except json.JSONDecodeError:
                st.error(e.response.text)
        return False


def refresh_token():
    """Refresh the access token using the refresh token"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/refresh",  # Updated to match your API endpoint
            json={"refresh": st.session_state.refresh_token}
        )
        response.raise_for_status()
        token_data = response.json()

        # Update access token and expiry time
        st.session_state.access_token = token_data["access"]
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4)
        return True
    except requests.exceptions.RequestException as e:
        # If refresh fails, user needs to log in again
        st.warning("Your session has expired. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        logout()
        return False


def verify_token():
    """Verify if the current token is valid"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/verify",  # Using your token verify endpoint
            json={"token": st.session_state.access_token}
        )
        return response.status_code == 200
    except:
        return False


def logout():
    """Clear authentication data from session state"""
    if 'access_token' in st.session_state:
        del st.session_state.access_token
    if 'refresh_token' in st.session_state:
        del st.session_state.refresh_token
    if 'token_expiry' in st.session_state:
        del st.session_state.token_expiry
    if 'username' in st.session_state:
        del st.session_state.username


def ensure_authenticated():
    """Check if user is authenticated, refresh token if needed"""
    if 'access_token' not in st.session_state:
        return False

    # Check if token is about to expire and refresh if needed
    if datetime.now() >= st.session_state.token_expiry:
        if not refresh_token():
            return False

    return True


def get_headers():
    """Returns the authorization headers with current token"""
    if not ensure_authenticated():
        st.error("You are not authenticated. Please log in.")
        st.stop()

    return {"Authorization": f"Bearer {st.session_state.access_token}",
            "Content-Type": "application/json"}


def make_request(method, endpoint, **kwargs):
    """Makes an authenticated API request and handles auth errors"""
    headers = get_headers()  # This will ensure token is valid
    url = f"{API_BASE_URL}{endpoint}"
    files = kwargs.pop('files', None)

    if files:
        headers.pop('Content-Type', None)

    try:
        response = requests.request(method, url, headers=headers, files=files, **kwargs)

        # Handle authentication errors specifically
        if response.status_code == 401:  # Unauthorized
            # Try to refresh the token once
            if refresh_token():
                # Update headers with new token and retry
                headers = get_headers()
                response = requests.request(method, url, headers=headers, files=files, **kwargs)
            else:
                st.error("Authentication failed. Please log in again.")
                st.stop()

        response.raise_for_status()

        if response.status_code == 204:  # No content
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API Request Failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                st.json(e.response.json())
            except json.JSONDecodeError:
                st.text(e.response.text)
        return None
    except json.JSONDecodeError:
        st.error("Failed to decode JSON response.")
        st.text(response.text)
        return None


# --- Streamlit UI ---
st.title("Meeting Analysis API Tester")

# Authentication UI in sidebar
with st.sidebar:
    st.subheader("Authentication")

    if 'access_token' in st.session_state:
        st.success(f"Logged in as {st.session_state.get('username', 'User')}")
        # Display token expiry information
        remaining = st.session_state.token_expiry - datetime.now()
        remaining_mins = max(0, int(remaining.total_seconds() / 60))
        remaining_secs = max(0, int(remaining.total_seconds() % 60))
        st.info(f"Token expires in: {remaining_mins}m {remaining_secs}s")

        if st.button("Logout"):
            logout()
            st.rerun()
    else:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

            if submitted:
                if login(username, password):
                    st.session_state.username = username
                    st.success("Login successful!")
                    st.rerun()

# Only show the main app if authenticated
if ensure_authenticated():
    # --- 1. Meetings ---
    st.header("1. Meetings")

    # Create Meeting Form
    with st.expander("Create New Meeting"):
        with st.form("create_meeting_form"):
            meeting_title = st.text_input("Meeting Title", "Test Meeting")
            meeting_date_input = st.date_input("Meeting Date", value=datetime.now().date())
            meeting_participants = st.text_area("Participants (Optional, comma-separated)", "Alice, Bob")
            submitted_create = st.form_submit_button("Create Meeting")

            if submitted_create:
                meeting_date_str = meeting_date_input.strftime('%Y-%m-%dT%H:%M:%S')
                payload = {
                    "title": meeting_title,
                    "meeting_date": meeting_date_str,
                    "participants": [p.strip() for p in meeting_participants.split(',') if p.strip()]
                }
                with st.spinner("Creating meeting..."):
                    result = make_request("POST", "/meetings/", json=payload)
                    if result:
                        st.success("Meeting Created Successfully!")
                        st.json(result)
                        st.session_state.created_meeting_id = result.get('id')

    # List/Select Meeting
    st.subheader("Select Meeting for Transcripts")
    if st.button("Load Existing Meetings"):
        with st.spinner("Loading meetings..."):
            meetings = make_request("GET", "/meetings/?limit=200")
            if meetings:
                st.session_state.meetings_list = meetings
            else:
                st.session_state.meetings_list = []

    if 'meetings_list' in st.session_state and st.session_state.meetings_list:
        meeting_options = {f"{m['title']} (ID: {m['id']})": m['id'] for m in st.session_state.meetings_list}
        selected_meeting_display = st.selectbox(
            "Select Meeting",
            options=meeting_options.keys(),
            index=0
        )
        st.session_state.selected_meeting_id = meeting_options[selected_meeting_display]
        st.write(f"Selected Meeting ID: {st.session_state.selected_meeting_id}")
    else:
        default_meeting_id = st.session_state.get('created_meeting_id', 0)
        st.session_state.selected_meeting_id = st.number_input(
            "Or Enter Meeting ID Manually",
            min_value=1,
            value=default_meeting_id if default_meeting_id else 1,
            step=1,
            help="Enter the ID of the meeting to add transcripts to."
        )

    st.divider()

    # --- 2. Transcripts ---
    st.header("2. Transcripts")

    if 'selected_meeting_id' not in st.session_state or not st.session_state.selected_meeting_id:
        st.warning("Please select or enter a Meeting ID above before adding transcripts.")
    else:
        meeting_id = st.session_state.selected_meeting_id

        # Submit Raw Text Form
        with st.expander("Submit Raw Transcript Text"):
            with st.form("raw_text_form"):
                raw_text = st.text_area("Paste Raw Transcript Text Here", height=200)
                submitted_text = st.form_submit_button("Submit Raw Text")

                if submitted_text and raw_text:
                    endpoint = f"/transcripts/{meeting_id}/"
                    payload = {"raw_text": raw_text}
                    with st.spinner("Submitting raw text transcript..."):
                        result = make_request("POST", endpoint, json=payload)
                        if result:
                            st.success("Raw Text Transcript Submitted!")
                            st.json(result)
                            st.session_state.created_transcript_id = result.get('id')

        # Upload File Form
        with st.expander("Upload Transcript File"):
            with st.form("upload_file_form", clear_on_submit=True):
                uploaded_file = st.file_uploader("Choose a transcript file (.txt, .vtt, etc.)")
                submitted_file = st.form_submit_button("Upload File")

                if submitted_file and uploaded_file is not None:
                    endpoint = f"/transcripts/{meeting_id}/upload/"
                    files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                    with st.spinner("Uploading transcript file..."):
                        result = make_request("POST", endpoint, files=files)
                        if result:
                            st.success("File Uploaded Successfully!")
                            st.json(result)
                            st.session_state.created_transcript_id = result.get('id')

        # Check Transcript Status
        st.subheader("Check Transcript Status")
        default_transcript_id = st.session_state.get('created_transcript_id', 0)
        transcript_id_for_status = st.number_input(
            "Transcript ID to Check Status",
            min_value=1,
            value=default_transcript_id if default_transcript_id else 1,
            step=1,
            key="status_check_tid"
        )
        if st.button("Get Status"):
            if transcript_id_for_status:
                endpoint = f"/transcripts/status/{transcript_id_for_status}/"
                with st.spinner(f"Checking status for transcript {transcript_id_for_status}..."):
                    result = make_request("GET", endpoint)
                    if result:
                        st.info(f"Status for Transcript {transcript_id_for_status}:")
                        st.json(result)

    st.divider()

    # --- 3. Analysis ---
    st.header("3. Analysis Results")
    st.info(
        "Note: Analysis is asynchronous. It might take some time after submitting a transcript for the analysis to be available.")

    # Get Analysis for a single Transcript
    st.subheader("Get Analysis by Transcript ID")
    default_analysis_tid = st.session_state.get('created_transcript_id', 0)
    transcript_id_for_analysis = st.number_input(
        "Transcript ID to Get Analysis",
        min_value=1,
        value=default_analysis_tid if default_analysis_tid else 1,
        step=1,
        key="analysis_check_tid"
    )
    if st.button("Get Transcript Analysis"):
        if transcript_id_for_analysis:
            endpoint = f"/analysis/transcript/{transcript_id_for_analysis}/"
            with st.spinner(f"Fetching analysis for transcript {transcript_id_for_analysis}..."):
                result = make_request("GET", endpoint)
                if result:
                    st.success(f"Analysis for Transcript {transcript_id_for_analysis}:")
                    st.json(result)
                else:
                    st.warning(
                        f"Could not retrieve analysis for transcript {transcript_id_for_analysis}. It might still be processing or not exist.")

    # Get Analyses for a Meeting
    st.subheader("Get All Analyses for a Meeting")
    if 'selected_meeting_id' in st.session_state and st.session_state.selected_meeting_id:
        meeting_id_for_analysis = st.session_state.selected_meeting_id
        st.write(f"Using selected Meeting ID: {meeting_id_for_analysis}")
        if st.button("Get All Analyses for Selected Meeting"):
            endpoint = f"/analysis/meeting/{meeting_id_for_analysis}/"
            with st.spinner(f"Fetching all analyses for meeting {meeting_id_for_analysis}..."):
                result = make_request("GET", endpoint)
                if result:
                    st.success(f"Analyses for Meeting {meeting_id_for_analysis}:")
                    st.json(result)
                elif result == []:
                    st.info(f"No analyses found for meeting {meeting_id_for_analysis}.")
else:
    st.info("Please log in using the sidebar to access the application.")