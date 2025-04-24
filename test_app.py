import streamlit as st
import requests
import json
from datetime import datetime, timedelta

# --- Page Configuration (MUST BE THE FIRST STREAMLIT COMMAND) ---
st.set_page_config(layout="wide") # MOVED HERE

# --- Configuration ---
API_BASE_URL = st.sidebar.text_input("API Base URL", "http://127.0.0.1:8000/api")


# --- Authentication Management ---
# (Keep existing login, refresh_token, verify_token, logout functions as they are)
def login(username, password):
    """Authenticate user and get JWT token"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/pair",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.refresh_token = token_data["refresh"]
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4) # Adjust expiry buffer if needed
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                st.error(e.response.json().get("detail", "Unknown error"))
            except json.JSONDecodeError:
                 st.error(f"Status {e.response.status_code}: {e.response.text}")
        return False


def refresh_token():
    """Refresh the access token using the refresh token"""
    if 'refresh_token' not in st.session_state:
        st.warning("No refresh token available. Please log in again.")
        logout()
        return False
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/refresh",
            json={"refresh": st.session_state.refresh_token}
        )
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4) # Reset expiry
        st.info("Token refreshed successfully.") # Optional user feedback
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Your session may have expired. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        logout() # Force logout if refresh fails
        return False

def verify_token():
    """Verify if the current token is valid"""
    if 'access_token' not in st.session_state: return False
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/verify",
            json={"token": st.session_state.access_token}
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def logout():
    """Clear authentication data from session state"""
    keys_to_remove = ['access_token', 'refresh_token', 'token_expiry', 'username',
                      'meetings_list', 'selected_meeting_id', 'created_transcript_id',
                      'current_meeting_transcripts'] # Also clear other session data on logout
    for key in keys_to_remove:
        if key in st.session_state:
            del st.session_state[key]
    st.success("Logged out.")


def ensure_authenticated():
    """Check if user is authenticated, refresh token if needed/expired"""
    if 'access_token' not in st.session_state:
        return False

    # Check if token is expired or very close to expiring (e.g., within 30 seconds)
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=30)):
        st.info("Access token expired or nearing expiry, attempting refresh...")
        if not refresh_token():
            return False # Refresh failed, user is effectively logged out

    # Optional: Verify token is still valid with the backend if needed (adds latency)
    # if not verify_token():
    #    st.warning("Token verification failed. Attempting refresh...")
    #    if not refresh_token(): return False

    return True


def get_headers(include_content_type=True):
    """Returns the authorization headers, ensures authentication first."""
    # This function doesn't need to call ensure_authenticated itself,
    # make_request should do that *before* calling get_headers.
    # This prevents potential premature error messages or stops.
    if 'access_token' not in st.session_state:
         # Should not happen if make_request calls ensure_authenticated first
         st.error("Authentication token missing unexpectedly.")
         st.stop()

    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


# --- MODIFIED make_request ---
def make_request(method, endpoint, json_data=None, data=None, files=None, **kwargs):
    """
    Makes an authenticated API request and handles auth errors.
    Can send JSON, form data, or files.
    Ensures user is authenticated before making the request.
    """
    # Ensure authenticated *before* trying to get headers or make call
    if not ensure_authenticated():
        st.error("Authentication required. Please log in.")
        # Don't st.stop() here, let the UI handle showing the login prompt
        return None # Return None to indicate failure due to auth

    # Determine Content-Type based on input
    include_content_type = True
    if files:
        include_content_type = False # requests handles multipart Content-Type
    elif data:
         include_content_type = False # requests handles form-urlencoded Content-Type

    headers = get_headers(include_content_type=include_content_type)
    url = f"{API_BASE_URL}{endpoint}"

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=json_data, # Use json parameter for JSON payload
            data=data,       # Use data parameter for form data
            files=files,     # Use files parameter for file uploads
            **kwargs
        )

        # Simplified Auth Handling: Assume 401 means token *might* be expired, try refresh once.
        if response.status_code == 401:
            st.warning("Received 401 Unauthorized. Attempting token refresh...")
            if refresh_token():
                # Retry the request with the new token
                headers = get_headers(include_content_type=include_content_type) # Get fresh headers
                st.info("Retrying request with new token...")
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                    data=data,
                    files=files,
                    **kwargs
                )
                # Re-check status after retry
                if response.status_code == 401:
                    st.error("Authentication still failed after token refresh. Please log in again.")
                    logout()
                    return None # Return None after failed retry
            else:
                # Refresh failed, logout() called within refresh_token()
                st.error("Token refresh failed. Please log in again.")
                return None # Return None after failed refresh


        response.raise_for_status() # Raise HTTPError for bad responses (4xx, 5xx) after handling 401

        # Handle different success status codes
        if response.status_code == 204: # No Content
            return True # Indicate success with no content explicitly if needed, or None
        elif response.text: # Check if there's any response body
            try:
                return response.json() # Attempt to parse JSON
            except json.JSONDecodeError:
                st.warning(f"Response status {response.status_code} received, but content is not valid JSON.")
                st.text(response.text[:500] + "...") # Show snippet of non-JSON response
                return response.text # Return raw text if not JSON
        else:
            # Successful response (e.g., 200 OK) but no body content
            return True # Indicate success explicitly if needed, or None

    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP Error: {http_err}")
        if http_err.response is not None:
            st.error(f"Status Code: {http_err.response.status_code}")
            try:
                # Try to display detail from API error response
                error_detail = http_err.response.json()
                if isinstance(error_detail, dict) and 'detail' in error_detail:
                    st.error(f"API Error Detail: {error_detail['detail']}")
                else:
                     st.json(error_detail) # Show full JSON if detail not found
            except json.JSONDecodeError:
                st.text(http_err.response.text) # Show raw text otherwise
        return None # Indicate failure
    except requests.exceptions.RequestException as req_err:
        st.error(f"Request Failed: {req_err}")
        return None # Indicate failure
    except Exception as e:
        st.error(f"An unexpected error occurred in make_request: {e}")
        return None # Indicate failure


# --- Streamlit UI ---
# st.set_page_config(layout="wide") # MOVED TO TOP

st.title("Meeting Insight API Interface")

# Authentication UI in sidebar
with st.sidebar:
    st.subheader("Authentication")

    # Check if logged in using access token presence (ensure_authenticated() will handle refresh)
    if 'access_token' in st.session_state:
        st.success(f"Logged in as {st.session_state.get('username', 'User')}")
        # Display token expiry information if available
        if 'token_expiry' in st.session_state:
             try:
                 remaining = st.session_state.token_expiry - datetime.now()
                 if remaining.total_seconds() > 0:
                     remaining_mins = max(0, int(remaining.total_seconds() / 60))
                     remaining_secs = max(0, int(remaining.total_seconds() % 60))
                     st.info(f"Token expires in: {remaining_mins}m {remaining_secs}s")
                 else:
                     st.warning("Access token has expired. Will refresh on next request.")
             except Exception: # Catch potential type errors if expiry is not datetime
                 st.warning("Could not determine token expiry.")

        if st.button("Logout"):
            logout()
            st.rerun() # Rerun to reflect logged-out state
    else:
        # Show login form only if not logged in
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Login")

            if submitted:
                if login(username, password):
                    st.session_state.username = username # Store username
                    st.success("Login successful!")
                    st.rerun() # Rerun to update UI
                # Error message handled within login function

# --- Main Application ---
# Check authentication status *before* rendering the main part of the app
if ensure_authenticated():

    tab1, tab2, tab3, tab4 = st.tabs(["▶️ Direct Submit & Analyze", "📁 Meetings", "📄 Transcripts", "📊 Analysis Lookup"])

    # --- TAB 1: Direct Submit & Analyze (NEW) ---
    with tab1:
        st.header("Direct Submit & Analyze")
        st.info("Submit transcript text or file directly. The system will automatically create the meeting, transcript, analyze the content, and show the results.")

        with st.form("direct_submit_form"): # Removed clear_on_submit=True to see results
            input_method = st.radio("Input Method", ["Paste Text", "Upload File"], index=0, key="direct_input_method")

            raw_text_input = None
            uploaded_file_input = None

            if input_method == "Paste Text":
                raw_text_input = st.text_area("Paste Raw Transcript Text Here", height=300, key="direct_raw_text")
            else:
                uploaded_file_input = st.file_uploader("Choose a transcript file (.txt, .vtt, etc.)", type=['txt', 'vtt', 'srt'], key="direct_file_upload") # Specify types

            submitted_direct = st.form_submit_button("🚀 Submit and Analyze")

            if submitted_direct:
                endpoint = "/analysis/process/direct/"
                form_data = None
                files_payload = None
                has_input = False

                if input_method == "Paste Text":
                    if raw_text_input and raw_text_input.strip():
                        # Send as form data using the 'data' parameter
                        form_data = {'raw_text': raw_text_input}
                        st.write("Submitting raw text...")
                        has_input = True
                    else:
                        st.warning("Please paste some transcript text.")

                elif input_method == "Upload File":
                    if uploaded_file_input is not None:
                        # Send as files using the 'files' parameter
                        files_payload = {'file': (uploaded_file_input.name, uploaded_file_input, uploaded_file_input.type)}
                        st.write(f"Submitting file: {uploaded_file_input.name}")
                        has_input = True
                    else:
                        st.warning("Please upload a transcript file.")

                # Proceed only if we have valid input
                if has_input:
                    with st.spinner("Processing transcript and generating analysis... This may take a minute."):
                        # Use make_request with appropriate parameters
                        result = make_request("POST", endpoint, data=form_data, files=files_payload)

                        # Check the result type: should be dict on success, None on failure
                        if isinstance(result, dict):
                            st.success("✅ Processing Complete!")
                            st.divider()
                            st.subheader("📊 Analysis Results")

                            # Display Meeting/Transcript Info
                            st.markdown(f"**Created Transcript ID:** `{result.get('transcript_id', 'N/A')}`")

                            # Nicely Formatted Output
                            col_summary, col_details = st.columns([2,1]) # Layout columns

                            with col_summary:
                                st.subheader("📝 Summary")
                                st.markdown(result.get('summary', '_No summary provided._'))

                                st.subheader("📌 Key Points")
                                key_points = result.get('key_points', [])
                                if key_points:
                                    st.markdown("\n".join(f"- {p}" for p in key_points))
                                else:
                                    st.write("_No key points extracted._")

                            with col_details:
                                st.subheader("❗ Action Item")
                                task = result.get('task')
                                responsible = result.get('responsible')
                                deadline = result.get('deadline') # Expects YYYY-MM-DD string or None

                                if task:
                                     st.markdown(f"**Task:** {task}")
                                     st.markdown(f"**Responsible:** {responsible if responsible else '_Not specified_'}")
                                     st.markdown(f"**Deadline:** {deadline if deadline else '_Not specified_'}")
                                else:
                                     st.info("No specific action item extracted.")

                                # Show original timestamps if available and needed
                                created_at_str = result.get('created_at')
                                updated_at_str = result.get('updated_at')
                                if created_at_str: st.caption(f"Analysis Created: {created_at_str}")
                                if updated_at_str: st.caption(f"Analysis Updated: {updated_at_str}")


                            # Raw JSON Expander
                            with st.expander("🔍 View Raw JSON Response"):
                                 st.json(result)

                        # Handle cases where make_request returned None (error occurred and was logged)
                        elif result is None:
                             st.error("❌ Processing failed. Check error messages above or API logs for details.")
                        # Handle unexpected return types from make_request (e.g., raw text)
                        elif not isinstance(result, dict):
                             st.error("❌ Processing failed. Unexpected response format received from API.")
                             st.text(result) # Show the raw response

    # --- TAB 2: Meetings ---
    with tab2:
        st.header("Manage Meetings")

        # Create Meeting Form
        with st.expander("➕ Create New Meeting"):
            with st.form("create_meeting_form"):
                meeting_title = st.text_input("Meeting Title", "Planning Session", key="mt_title")
                meeting_date_input = st.date_input("Meeting Date", value=datetime.now().date(), key="mt_date")
                meeting_time_input = st.time_input("Meeting Time", value=datetime.now().time(), key="mt_time")
                meeting_participants = st.text_area("Participants (Optional, comma-separated)", "Alice, Bob", key="mt_participants")
                # Add Metadata input if desired
                # meeting_metadata_json = st.text_area("Metadata (Optional, JSON format)", "{}", key="mt_metadata")
                submitted_create = st.form_submit_button("Create Meeting")

                if submitted_create and meeting_title.strip():
                    meeting_datetime = datetime.combine(meeting_date_input, meeting_time_input)
                    meeting_date_str = meeting_datetime.isoformat() # ISO 8601 format
                    participants_list = [p.strip() for p in meeting_participants.split(',') if p.strip()] or None

                    # Parse metadata JSON (add error handling)
                    # metadata_dict = {}
                    # try:
                    #     if meeting_metadata_json.strip():
                    #         metadata_dict = json.loads(meeting_metadata_json)
                    # except json.JSONDecodeError:
                    #     st.error("Invalid JSON format for Metadata.")
                    #     metadata_dict = None # Prevent API call with invalid JSON

                    # if metadata_dict is not None: # Proceed only if metadata is valid or empty
                    payload = {
                        "title": meeting_title,
                        "meeting_date": meeting_date_str,
                        "participants": participants_list,
                        # "metadata": metadata_dict
                    }
                    with st.spinner("Creating meeting..."):
                        result = make_request("POST", "/meetings/", json_data=payload)
                        if isinstance(result, dict): # Check if result is a dictionary (expected success)
                            st.success("Meeting Created Successfully!")
                            st.json(result)
                            # Update selected ID to the newly created one
                            st.session_state.selected_meeting_id = result.get('id')
                            # Optionally reload meeting list
                            st.session_state.meetings_list = None # Force reload on next click

        # List/Select Meeting
        st.subheader("Select or View Existing Meetings")
        if st.button("🔄 Load/Refresh Meeting List", key="load_meetings"):
            with st.spinner("Loading meetings..."):
                meetings = make_request("GET", "/meetings/?limit=200") # Fetch more if needed
                if isinstance(meetings, list): # Check if API returned a list
                    st.session_state.meetings_list = meetings
                    st.success(f"Loaded {len(meetings)} meetings.")
                    if not meetings:
                        st.info("No meetings found.")
                else:
                    # Error handled by make_request, maybe add context here
                    st.session_state.meetings_list = [] # Clear list on error
                    st.warning("Could not load meetings.")

        # Display dropdown only if meetings_list exists and is not empty
        if 'meetings_list' in st.session_state and st.session_state.meetings_list:
            # Sort meetings, most recent first based on meeting_date or created_at
            try:
                 sorted_meetings = sorted(
                     st.session_state.meetings_list,
                     key=lambda m: m.get('meeting_date', m.get('created_at', '')), # Use meeting_date, fallback to created_at
                     reverse=True
                 )
            except TypeError: # Handle potential comparison errors if dates are missing/malformed
                 st.warning("Could not sort meetings by date.")
                 sorted_meetings = st.session_state.meetings_list

            meeting_options = {
                f"{m.get('title', 'Untitled')} (ID: {m.get('id', 'N/A')}, Date: {m.get('meeting_date', 'N/A')[:16]})": m.get('id') # Format date for display
                for m in sorted_meetings
            }

            # Find the index of the currently selected meeting ID, default to 0
            current_selection_id = st.session_state.get('selected_meeting_id')
            options_list = list(meeting_options.keys())
            try:
                current_index = options_list.index(next(k for k, v in meeting_options.items() if v == current_selection_id)) if current_selection_id else 0
            except (StopIteration, ValueError):
                current_index = 0 # Default to first item if ID not found or invalid

            selected_meeting_display = st.selectbox(
                "Select Meeting",
                options=options_list,
                index=current_index,
                key="meeting_select"
            )
            if selected_meeting_display: # Check if selection is made
                 st.session_state.selected_meeting_id = meeting_options[selected_meeting_display]
                 st.info(f"Selected Meeting ID: `{st.session_state.selected_meeting_id}`")

                 # Optionally display details of the selected meeting
                 selected_meeting_details = next((m for m in st.session_state.meetings_list if m.get('id') == st.session_state.selected_meeting_id), None)
                 if selected_meeting_details:
                     with st.expander("Selected Meeting Details"):
                         st.json(selected_meeting_details)

        else:
            st.info("No meetings loaded. Use the 'Load/Refresh' button or create a new meeting.")

    # --- TAB 3: Transcripts ---
    with tab3:
        st.header("Manage Transcripts")

        # Check if a meeting is selected before showing transcript options
        current_meeting_id = st.session_state.get('selected_meeting_id')

        if not current_meeting_id:
            st.warning("⚠️ Please select a Meeting from the 'Meetings' tab first!")
        else:
            st.info(f"Actions will apply to Meeting ID: `{current_meeting_id}` (Selected in 'Meetings' tab)")

            # Submit Raw Text Form
            with st.expander("➕ Submit Raw Transcript Text"):
                with st.form("raw_text_form"):
                    raw_text = st.text_area("Paste Raw Transcript Text Here", height=200, key="ts_raw_text")
                    submitted_text = st.form_submit_button("Submit Raw Text")

                    if submitted_text and raw_text and raw_text.strip():
                        endpoint = f"/transcripts/{current_meeting_id}/"
                        payload = {"raw_text": raw_text}
                        with st.spinner("Submitting raw text transcript..."):
                            result = make_request("POST", endpoint, json_data=payload)
                            if isinstance(result, dict):
                                st.success("Raw Text Transcript Submitted!")
                                st.json(result)
                                st.session_state.created_transcript_id = result.get('id') # Store last created ID
                                st.session_state.current_meeting_transcripts = None # Force reload

            # Upload File Form
            with st.expander("📄 Upload Transcript File"):
                with st.form("upload_file_form"):
                    uploaded_file = st.file_uploader("Choose a transcript file (.txt, .vtt, etc.)", type=['txt','vtt','srt'], key="ts_upload")
                    submitted_file = st.form_submit_button("Upload File")

                    if submitted_file and uploaded_file is not None:
                        endpoint = f"/transcripts/{current_meeting_id}/upload/"
                        files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                        with st.spinner("Uploading transcript file..."):
                            result = make_request("POST", endpoint, files=files)
                            if isinstance(result, dict):
                                st.success("File Uploaded Successfully!")
                                st.json(result)
                                st.session_state.created_transcript_id = result.get('id') # Store last created ID
                                st.session_state.current_meeting_transcripts = None # Force reload


            st.divider()
            st.subheader("View Transcripts for Selected Meeting")
            # Reload transcripts if the list is not in session state or if button clicked
            if 'current_meeting_transcripts' not in st.session_state or st.button("🔄 Load/Refresh Transcripts", key="load_transcripts"):
                endpoint = f"/transcripts/meeting/{current_meeting_id}/"
                with st.spinner(f"Loading transcripts for meeting {current_meeting_id}..."):
                    transcripts = make_request("GET", endpoint)
                    if isinstance(transcripts, list):
                        st.session_state.current_meeting_transcripts = transcripts
                        st.success(f"Loaded {len(transcripts)} transcripts.")
                        if not transcripts:
                             st.info("No transcripts found for this meeting.")
                    else:
                         st.session_state.current_meeting_transcripts = [] # Clear on error
                         st.warning("Could not load transcripts.")

            # Display dataframe if transcripts are loaded
            if 'current_meeting_transcripts' in st.session_state and st.session_state.current_meeting_transcripts:
                 st.dataframe(st.session_state.current_meeting_transcripts)


            st.subheader("Check Transcript Status by ID")
            # Use the last created ID as default if available
            default_ts_id = st.session_state.get('created_transcript_id', 1 if 'current_meeting_transcripts' in st.session_state and st.session_state.current_meeting_transcripts else 0) # Default logic needs refinement
            if default_ts_id == 0: default_ts_id = 1 # Ensure min_value is met

            transcript_id_for_status = st.number_input(
                "Transcript ID to Check Status",
                min_value=1,
                value=default_ts_id,
                step=1,
                key="status_check_tid"
            )
            if st.button("Get Status", key="get_status_btn"):
                if transcript_id_for_status:
                    endpoint = f"/transcripts/status/{transcript_id_for_status}/"
                    with st.spinner(f"Checking status for transcript {transcript_id_for_status}..."):
                        result = make_request("GET", endpoint)
                        if isinstance(result, dict):
                            st.info(f"Status for Transcript {transcript_id_for_status}:")
                            st.json(result)
                        # Error handled by make_request

    # --- TAB 4: Analysis Lookup ---
    with tab4:
        st.header("Lookup Analysis Results")

        # Get Analysis for a single Transcript
        st.subheader("Get Analysis by Transcript ID")
        # Use last created transcript ID as default
        default_analysis_tid = st.session_state.get('created_transcript_id', 1)
        transcript_id_for_analysis = st.number_input(
            "Transcript ID",
            min_value=1,
            value=default_analysis_tid,
            step=1,
            key="analysis_check_tid"
        )

        col1_lookup, col2_lookup = st.columns(2)

        with col1_lookup:
            if st.button("🔍 Get Transcript Analysis", key="get_analysis"):
                if transcript_id_for_analysis:
                    endpoint = f"/analysis/transcript/{transcript_id_for_analysis}/"
                    with st.spinner(f"Fetching analysis for transcript {transcript_id_for_analysis}..."):
                        result = make_request("GET", endpoint)
                        if isinstance(result, dict):
                            st.success(f"Analysis for Transcript {transcript_id_for_analysis}:")
                            # Display formatted result similar to direct analysis tab
                            st.subheader("📝 Summary")
                            st.markdown(result.get('summary', '_No summary provided._'))
                            st.subheader("📌 Key Points")
                            key_points = result.get('key_points', [])
                            if key_points: st.markdown("\n".join(f"- {p}" for p in key_points))
                            else: st.write("_No key points extracted._")
                            st.subheader("❗ Action Item")
                            task=result.get('task'); resp=result.get('responsible'); dead=result.get('deadline')
                            if task:
                                st.markdown(f"**Task:** {task}")
                                st.markdown(f"**Responsible:** {resp if resp else '_Not specified_'}")
                                st.markdown(f"**Deadline:** {dead if dead else '_Not specified_'}")
                            else: st.info("No specific action item extracted.")
                            with st.expander("🔍 View Raw JSON"): st.json(result)
                        else:
                             # Check if the response suggests "not found yet" vs "transcript not found"
                             st.warning(f"Analysis not found or error retrieving analysis for transcript {transcript_id_for_analysis}. Check ID and logs.")


        with col2_lookup:
            # Generate Analysis for an existing transcript
            if st.button("⚙️ Generate Analysis Now", key="generate_analysis", help="Trigger analysis generation if it hasn't run or needs updating"):
                if transcript_id_for_analysis:
                    endpoint = f"/analysis/generate/{transcript_id_for_analysis}/"
                    with st.spinner(f"Triggering analysis generation for transcript {transcript_id_for_analysis}..."):
                        result = make_request("POST", endpoint) # POST request
                        if isinstance(result, dict):
                            st.success(f"Analysis generation triggered/completed successfully for Transcript {transcript_id_for_analysis}:")
                            st.json(result) # Show the resulting analysis object
                        # Error handled by make_request

        st.divider()
        # Get Analyses for a Meeting
        st.subheader("Get All Analyses for a Meeting")
        # Use the selected meeting ID from the Meetings tab
        lookup_meeting_id = st.session_state.get('selected_meeting_id')

        if lookup_meeting_id:
             st.info(f"Using selected Meeting ID: `{lookup_meeting_id}` (Change in 'Meetings' tab)")
             if st.button("🔍 Get All Analyses for Selected Meeting", key="get_meeting_analysis"):
                 endpoint = f"/analysis/meeting/{lookup_meeting_id}/"
                 with st.spinner(f"Fetching all analyses for meeting {lookup_meeting_id}..."):
                     result = make_request("GET", endpoint)
                     if isinstance(result, list):
                         st.success(f"Found {len(result)} Analyses for Meeting {lookup_meeting_id}:")
                         if result:
                            st.dataframe(result) # Display as dataframe
                            with st.expander("🔍 View Raw JSON"): st.json(result)
                         else:
                            st.info(f"No analyses found for meeting {lookup_meeting_id}.")
                     # Error handled by make_request
        else:
             st.warning("⚠️ Please select a Meeting from the 'Meetings' tab first.")

# --- Footer/Login Prompt ---
elif 'access_token' not in st.session_state: # Only show login prompt if not logged in
    st.info("👋 Welcome! Please log in using the sidebar to access the application features.")
# If ensure_authenticated returned False but token exists, errors/refresh attempts were handled inside functions