# app.py
import streamlit as st
import requests
import json
import time
from datetime import datetime, date, timedelta # Ensure date is imported
from typing import Optional, List, Any
import io
import math # For calculating pages

# --- (Keep all previous functions: login, refresh_token, logout, ensure_authenticated, get_headers, make_request, display_analysis_results) ---
# --- (No changes needed in those core functions) ---

# Configure Streamlit page
st.set_page_config(layout="wide", page_title="Meeting Analysis")

# --- Global Configuration ---
API_BASE_URL = st.sidebar.text_input("API Base URL", "http://127.0.0.1:8000/api")
DEFAULT_ANALYSIS_LIMIT = 5 # How many analysis results per page


# --- Core Functions (Authentication & API Request) ---

def login(username, password):
    """Handles user login and stores tokens in session state."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/pair",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.refresh_token = token_data["refresh"]
        # Set a reasonable expiry time (match backend JWT settings if possible)
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55) # Example: slightly less than 24h
        st.session_state.logged_in = True
        st.session_state.username = username
        st.success("Login successful!")
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json().get("detail", "Unknown error")
                st.error(f"API Error: {error_detail}")
            except json.JSONDecodeError:
                 st.error(f"API Error: Status {e.response.status_code} - {e.response.text}")
        # Clear potentially invalid state on failure
        logout(silent=True) # Use silent logout to prevent redundant messages
        return False

def refresh_token():
    """Refreshes the access token using the refresh token."""
    if 'refresh_token' not in st.session_state:
        st.warning("No refresh token available. Please log in again.")
        logout() # Force logout if refresh impossible
        return False
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/refresh",
            json={"refresh": st.session_state.refresh_token}
        )
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        # Update expiry time after refresh
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55)
        st.session_state.logged_in = True # Ensure logged_in state is correct
        st.info("Token refreshed successfully.")
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Session expired or token invalid. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None and e.response.status_code in [401, 400]:
             st.error("Reason: Refresh token is invalid or has expired.")
        logout() # Force logout on refresh failure
        return False

def logout(silent=False):
    """Clears authentication and UI session state."""
    if not silent:
        st.info("Logging out...")
    keys_to_remove = [
        # Auth
        'access_token', 'refresh_token', 'token_expiry', 'logged_in', 'username',
        # New Analysis Tab State
        'analysis_tab_meetings_list', 'select_meeting_dropdown', 'meeting_action',
        'just_created_meeting_id',
        # History Tab State
        'history_meetings_list', 'selected_meeting_analyses', '_cached_analysis_meeting_id',
        'selected_meeting_id_history', 'history_meeting_select',
        'history_filter_title', 'history_filter_date_from', 'history_filter_date_to', # History filters
        'analysis_results_offset', 'analysis_results_limit', 'analysis_results_total_count', # History pagination
    ]
    for key in keys_to_remove:
        if key in st.session_state:
            try: del st.session_state[key]
            except KeyError: pass
    if not silent:
        st.success("Logged out successfully.")

def ensure_authenticated():
    """Checks if user is logged in and token is valid/refreshed."""
    if not st.session_state.get('logged_in', False) or 'access_token' not in st.session_state:
        return False # Not logged in

    # Check token expiry with a buffer
    buffer_seconds = 60 # Refresh 1 minute before potential expiry
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=buffer_seconds)):
        st.info("Access token nearing expiry or expired, attempting refresh...")
        if not refresh_token():
            st.warning("Session expired. Please log in again.")
            st.rerun() # Rerun to force login state update
            return False # Refresh failed
    return True # Authenticated and token valid/refreshed

def get_headers(include_content_type=True):
    """Constructs standard request headers with JWT."""
    if 'access_token' not in st.session_state:
         st.error("Authentication token missing unexpectedly. Please log in.")
         logout() # Force logout
         st.rerun()
         return None
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        # Only add Content-Type if explicitly needed (e.g., for JSON body)
        headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json" # Always accept JSON responses
    return headers

def make_request(method, endpoint, json_data=None, data=None, files=None, params=None, timeout=30, **kwargs):
    """Makes an authenticated API request, handling auth refresh and errors."""
    # Allow explicit params argument
    if not ensure_authenticated():
        return None

    include_content_type = json_data is not None and not files and not data
    headers = get_headers(include_content_type=include_content_type)
    if headers is None: return None

    # Combine explicit params with GET params from json_data if needed
    request_params = params if params is not None else {}
    if method.upper() == 'GET' and json_data is not None:
        request_params.update(json_data) # Add json_data to params for GET
        json_data = None # Clear json_data

    url = f"{API_BASE_URL}{endpoint}"
    attempt_retry = True

    while attempt_retry:
        attempt_retry = False
        try:
            response = requests.request(
                method, url, headers=headers, json=json_data, data=data,
                files=files, params=request_params, timeout=timeout, **kwargs # Pass params here
            )
            if response.status_code == 401:
                st.warning("Received 401 Unauthorized. Attempting token refresh...")
                if refresh_token():
                    headers = get_headers(include_content_type=include_content_type) # Refresh headers
                    if headers is None: return None
                    st.info("Retrying request with refreshed token...")
                    attempt_retry = True
                    continue
                else:
                    st.error("Token refresh failed during retry. Please log in again.")
                    st.rerun()
                    return None

            response.raise_for_status()

            if response.status_code == 204: return True
            elif response.status_code in [200, 201, 202]:
                if response.text:
                    try: return response.json()
                    except json.JSONDecodeError:
                        st.warning(f"API OK ({response.status_code}) but not valid JSON.")
                        return response.text
                else: return True
            else:
                st.warning(f"Unexpected success status code {response.status_code}")
                return response.text if response.text else True

        except requests.exceptions.HTTPError as http_err:
            st.error(f"HTTP Error: {http_err}")
            if http_err.response is not None:
                st.error(f"Status Code: {http_err.response.status_code}")
                try:
                    error_detail = http_err.response.json()
                    detail_msg = error_detail.get('detail', json.dumps(error_detail))
                    if isinstance(detail_msg, list): detail_msg = "; ".join(map(str, detail_msg))
                    elif not isinstance(detail_msg, str): detail_msg = json.dumps(detail_msg)
                    st.error(f"API Error Detail: {detail_msg}")
                except json.JSONDecodeError: st.error(f"Raw Error Response:\n{http_err.response.text[:500]}")
            return None
        except requests.exceptions.ConnectionError as e: st.error(f"Connection Error: {e}"); return None
        except requests.exceptions.Timeout as e: st.error(f"Request Timed Out: {e}"); return None
        except requests.exceptions.RequestException as e: st.error(f"Request Failed: {e}"); return None
        except Exception as e: st.error(f"Unexpected error in make_request: {e}"); import traceback; st.error(traceback.format_exc()); return None
    return None


# --- Display Function (no changes needed) ---
def display_analysis_results(result, participants: Optional[List[Any]] = None, transcript_title: Optional[str] = None, include_json_expander=True):
    # ... (keep existing implementation) ...
    if not isinstance(result, dict):
        st.warning("Invalid analysis result format received.")
        st.json(result)
        return

    st.markdown(f"**Transcript ID:** `{result.get('transcript_id', 'N/A')}`")
    if transcript_title:
         st.markdown(f"**Transcript Title:** *{transcript_title}*")

    col_summary, col_details = st.columns([2, 1])

    with col_summary:
        st.subheader("📝 Summary")
        summary = result.get('summary')
        st.markdown(summary if summary else '_No summary provided._')

        st.subheader("📌 Key Points")
        key_points = result.get('key_points')
        if key_points and isinstance(key_points, list) and len(key_points) > 0:
             st.markdown("\n".join(f"- {p}" for p in key_points))
        else:
            st.write("_No key points extracted._")

    with col_details:
        st.subheader("❗ Action Item")
        task = result.get('task')
        responsible = result.get('responsible')
        deadline = result.get('deadline') # Should be YYYY-MM-DD string or None from API
        if task or responsible or deadline:
             st.markdown(f"**Task:** {task if task else '_Not specified_'}")
             st.markdown(f"**Responsible:** {responsible if responsible else '_Not specified_'}")
             deadline_str = deadline
             if deadline:
                 try:
                    # API should return YYYY-MM-DD, parse and format
                    deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").date()
                    deadline_str = deadline_dt.strftime("%B %d, %Y") # e.g., October 27, 2023
                 except (ValueError, TypeError) as parse_err:
                     st.warning(f"Could not format deadline date '{deadline}': {parse_err}")
                     deadline_str = str(deadline) # Fallback
             st.markdown(f"**Deadline:** {deadline_str if deadline_str else '_Not specified_'}")
        else:
             st.info("No specific action item extracted.")

        st.subheader("👥 Participants (Meeting Level)")
        if participants and isinstance(participants, list) and len(participants) > 0:
            try:
                participants_str = ', '.join(map(str, participants))
                st.markdown(f"{participants_str}")
            except Exception as e:
                st.warning(f"Could not format participants list: {e}")
                st.markdown("_Error displaying participants._")
        elif participants == []:
             st.markdown("_No participants listed for this meeting._")
        else:
            st.markdown("_Participants data not available for this meeting._")

        # Timestamps for the Analysis Result record itself
        st.caption("---")
        created_at_str = result.get('created_at')
        updated_at_str = result.get('updated_at')
        created_dt = None
        try:
            if created_at_str:
                if isinstance(created_at_str, str) and not created_at_str.endswith(('Z', '+00:00', '-00:00')):
                    created_at_str += 'Z' # Assume UTC if timezone missing
                created_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                st.caption(f"Analyzed: {created_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            if updated_at_str:
                if isinstance(updated_at_str, str) and not updated_at_str.endswith(('Z', '+00:00', '-00:00')):
                     updated_at_str += 'Z'
                updated_dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                # Show updated time if different from created time
                if created_dt is None or abs((updated_dt - created_dt).total_seconds()) > 5:
                     st.caption(f"Updated: {updated_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except (ValueError, TypeError) as parse_err:
             st.warning(f"Could not parse analysis timestamp: {parse_err}")
             if created_at_str: st.caption(f"Analyzed (raw): {created_at_str}")
             if updated_at_str: st.caption(f"Updated (raw): {updated_at_str}")

    # Expander for raw JSON
    if include_json_expander:
        with st.expander("🔍 View Raw JSON Response (Analysis Result)"):
            st.json(result)


# --- Main Application UI ---
st.title("🗣️ Meeting Analysis Application")

# --- Sidebar (Authentication - unchanged) ---
with st.sidebar:
    # ... (keep existing sidebar auth logic) ...
    st.subheader("Authentication")
    if st.session_state.get('logged_in', False):
        st.success(f"Logged in as **{st.session_state.get('username', 'User')}**")
        if 'token_expiry' in st.session_state:
             try:
                 now = datetime.now()
                 expiry = st.session_state.token_expiry
                 remaining = expiry - now
                 if remaining.total_seconds() > 0:
                     total_seconds = int(remaining.total_seconds())
                     mins, secs = divmod(total_seconds, 60)
                     expiry_str = f"{mins}m {secs}s"
                     st.info(f"Session expires in approx: {expiry_str}")
                 else:
                     st.warning("Session may have expired.")
             except Exception as e:
                 st.warning(f"Could not display token expiry: {e}")

        if st.button("Logout", key="logout_button"):
            logout()
            st.rerun()
    else:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Login")
            if submitted:
                if login(username, password):
                    st.rerun()


# --- Main Content Area (Only if Logged In) ---
if st.session_state.get('logged_in', False):

    # --- Initialize session state keys if they don't exist ---
    if 'meeting_action' not in st.session_state: st.session_state.meeting_action = "Select Existing Meeting"
    if 'select_meeting_dropdown' not in st.session_state: st.session_state.select_meeting_dropdown = "-- Select a Meeting --"
    # History tab state
    if 'history_filter_title' not in st.session_state: st.session_state.history_filter_title = ""
    if 'history_filter_date_from' not in st.session_state: st.session_state.history_filter_date_from = None
    if 'history_filter_date_to' not in st.session_state: st.session_state.history_filter_date_to = None
    if 'analysis_results_offset' not in st.session_state: st.session_state.analysis_results_offset = 0
    if 'analysis_results_limit' not in st.session_state: st.session_state.analysis_results_limit = DEFAULT_ANALYSIS_LIMIT
    if 'analysis_results_total_count' not in st.session_state: st.session_state.analysis_results_total_count = 0

    # --- Handle state transition after meeting creation ---
    just_created_meeting_id = st.session_state.pop('just_created_meeting_id', None)
    if just_created_meeting_id:
        st.session_state.meeting_action = "Select Existing Meeting" # Prepare state for next run


    # --- Define Tabs ---
    tab_analysis, tab_history = st.tabs(["✨ New Analysis", "📂 History"])

    # ==============================
    # == New Analysis Tab Logic (Unchanged from previous correction) ==
    # ==============================
    with tab_analysis:
        # --- (Keep existing Step 1 & Step 2 logic from the previous correction) ---
        st.header("Submit New Transcript for Analysis")
        st.subheader("Step 1: Select or Create Meeting")
        meeting_action = st.radio( "Choose Action", ["Select Existing Meeting", "Create New Meeting"], key="meeting_action", horizontal=True)
        selected_meeting_id = None
        selected_meeting_title = None

        if st.session_state.meeting_action == "Select Existing Meeting":
            if 'analysis_tab_meetings_list' not in st.session_state:
                with st.spinner("Loading meetings..."):
                    meetings_data = make_request("GET", "/meetings/?limit=500")
                    if isinstance(meetings_data, list): st.session_state.analysis_tab_meetings_list = meetings_data
                    else: st.session_state.analysis_tab_meetings_list = []; st.warning("Could not load meetings.")
            meetings_list = st.session_state.get('analysis_tab_meetings_list', [])
            if meetings_list:
                try: sorted_meetings = sorted(meetings_list, key=lambda m: m.get('meeting_date', '1970-01-01T00:00:00Z'), reverse=True)
                except Exception: sorted_meetings = meetings_list
                meeting_options = {"-- Select a Meeting --": None}
                target_label_for_new_meeting = None
                for m in sorted_meetings:
                    m_id=m.get('id'); m_title=m.get('title','Untitled'); m_date_str=m.get('meeting_date','')
                    try: m_date_fmt = datetime.fromisoformat(m_date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                    except: m_date_fmt = m_date_str
                    label = f"{m_title} (ID: {m_id} | {m_date_fmt})"
                    meeting_options[label] = m_id
                    if just_created_meeting_id and m_id == just_created_meeting_id: target_label_for_new_meeting = label
                options_list = list(meeting_options.keys()); select_index = 0
                if target_label_for_new_meeting:
                    try: select_index = options_list.index(target_label_for_new_meeting)
                    except ValueError: pass
                elif 'select_meeting_dropdown' in st.session_state and st.session_state.select_meeting_dropdown in options_list:
                    try: select_index = options_list.index(st.session_state.select_meeting_dropdown)
                    except ValueError: pass
                selected_label = st.selectbox("Select Meeting", options=options_list, index=select_index, key="select_meeting_dropdown")
                selected_meeting_id = meeting_options.get(selected_label)
                if selected_meeting_id: selected_meeting_title = selected_label.split(" (ID:")[0]
            else: st.info("No existing meetings found.")

        elif st.session_state.meeting_action == "Create New Meeting":
            with st.form("create_meeting_form"):
                new_title = st.text_input("Meeting Title*", key="new_meeting_title_input")
                submitted_create = st.form_submit_button("Create Meeting")
                if submitted_create:
                    if not new_title.strip(): st.warning("Meeting Title is required.")
                    else:
                        payload = {"title": new_title}
                        if payload:
                            with st.spinner("Creating meeting..."):
                                response = make_request("POST", "/meetings/", json_data=payload)
                                if isinstance(response, dict) and 'id' in response:
                                    st.success(f"Meeting '{response.get('title')}' created (ID: {response['id']}). Switching...")
                                    if 'analysis_tab_meetings_list' not in st.session_state: st.session_state.analysis_tab_meetings_list = []
                                    st.session_state.analysis_tab_meetings_list.append(response)
                                    st.session_state.just_created_meeting_id = response['id'] # Set flag
                                    st.rerun() # Rerun
                                else: st.error("Failed to create meeting.")

        if selected_meeting_id:
            st.divider()
            st.subheader(f"Step 2: Add Transcript to '{selected_meeting_title or f'Meeting ID: {selected_meeting_id}'}'")
            with st.form("transcript_submit_form", clear_on_submit=True):
                input_method = st.radio("Input Method", ["Paste Text", "Upload File"], index=0, key="transcript_input_method", horizontal=True)
                raw_text_input=None; uploaded_file_input=None
                if input_method == "Paste Text": raw_text_input = st.text_area("Paste Text", height=300, key="transcript_raw_text")
                else: uploaded_file_input = st.file_uploader("Choose File", type=['txt', 'pdf', 'md', 'docx'], key="transcript_file_upload")
                submitted_transcript = st.form_submit_button("🚀 Submit for Analysis")
            if submitted_transcript:
                initial_response=None; request_json_payload=None; files_payload=None; endpoint=None
                if input_method=="Paste Text":
                    if raw_text_input and raw_text_input.strip(): endpoint=f"/transcripts/{selected_meeting_id}/"; request_json_payload={'raw_text': raw_text_input}; st.write("Submitting text...")
                    else: st.warning("Please paste text.")
                elif input_method=="Upload File":
                    if uploaded_file_input: endpoint=f"/transcripts/{selected_meeting_id}/upload/"; files_payload={'file': (uploaded_file_input.name, uploaded_file_input.getvalue(), uploaded_file_input.type)}; st.write(f"Uploading {uploaded_file_input.name}...")
                    else: st.warning("Please upload file.")
                if endpoint and (request_json_payload or files_payload):
                    with st.spinner("Submitting..."): initial_response = make_request("POST", endpoint, json_data=request_json_payload, files=files_payload)
                    if isinstance(initial_response, dict) and 'id' in initial_response:
                        transcript_id=initial_response['id']; initial_status=initial_response['processing_status']; retrieved_meeting_id=initial_response.get('meeting_id')
                        st.success(f"✅ Submitted! Transcript ID: {transcript_id}. Queued."); st.info(f"Status: {initial_status}")
                        status_placeholder=st.status(f"Processing {transcript_id}...", expanded=True); max_attempts=60; poll_interval=5; attempts=0; final_analysis_result=None; final_participants=None; final_transcript_title=None; polling_endpoint=f"/transcripts/status/{transcript_id}/"; analysis_endpoint=f"/analysis/transcript/{transcript_id}/"; current_status=initial_status
                        while attempts < max_attempts:
                            attempts += 1; time.sleep(poll_interval); status_placeholder.write(f"Checking... ({attempts}/{max_attempts})"); status_response=make_request("GET", polling_endpoint)
                            if isinstance(status_response, dict) and 'processing_status' in status_response:
                                current_status=status_response['processing_status']; final_transcript_title=status_response.get('title');
                                if not retrieved_meeting_id: retrieved_meeting_id = status_response.get('meeting_id')
                                status_placeholder.update(label=f"Transcript {transcript_id} Status: {current_status}")
                                if current_status=="COMPLETED":
                                    status_placeholder.write("Fetching results..."); analysis_result=make_request("GET", analysis_endpoint)
                                    if isinstance(analysis_result, dict):
                                        final_analysis_result=analysis_result; status_placeholder.write("Results received.")
                                        if retrieved_meeting_id:
                                            meeting_details=make_request("GET", f"/meetings/{retrieved_meeting_id}/")
                                            if isinstance(meeting_details, dict): final_participants = meeting_details.get('participants')
                                            else: status_placeholder.warning(f"Couldn't fetch meeting {retrieved_meeting_id} details.")
                                        status_placeholder.update(label=f"Analysis Complete!", state="complete", expanded=False); st.success("📊 Processing complete.")
                                    else: st.error(f"Failed to fetch results from {analysis_endpoint}."); status_placeholder.error("Result fetch failed.").update(label="Error", state="error")
                                    break
                                elif current_status=="FAILED": status_placeholder.error(f"Failed: {status_response.get('processing_error','Unknown')}"); status_placeholder.update(label="Failed", state="error"); break
                                elif current_status in ["PENDING","PROCESSING"]: pass
                                else: status_placeholder.warning(f"Unexpected status: {current_status}"); break
                            else: status_placeholder.warning(f"Status check failed ({attempts}).");
                            if attempts > 5 and status_response is None: status_placeholder.error("Status checks failed."); status_placeholder.update(label="Error", state="error"); break
                        if attempts == max_attempts and current_status not in ["COMPLETED", "FAILED"]: status_placeholder.warning("Timeout."); status_placeholder.update(label="Timeout", state="warning")
                        if final_analysis_result: display_analysis_results(final_analysis_result, participants=final_participants, transcript_title=final_transcript_title)
                        if 'history_meetings_list' in st.session_state: del st.session_state['history_meetings_list'] # Refresh history cache
                    elif initial_response is None: st.error("❌ Submission failed. API error.")
                    else: st.error(f"❌ Submission failed. Response:"); st.json(initial_response)
                elif submitted_transcript: st.warning("No valid input.")
        else: st.info("Select or create meeting first.")


    # ==============================
    # == History Tab Logic ==
    # ==============================
    with tab_history:
        st.header("View Past Analysis Results")

        # --- Meeting Filters ---
        st.subheader("Filter Meetings")
        filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
        with filter_col1:
            st.session_state.history_filter_title = st.text_input(
                "Filter by Title (contains):",
                value=st.session_state.history_filter_title, # Use state
                key="hist_filter_title_input"
            )
        with filter_col2:
            st.session_state.history_filter_date_from = st.date_input(
                "Date From:",
                value=st.session_state.history_filter_date_from, # Use state
                key="hist_filter_date_from_input"
            )
        with filter_col3:
             st.session_state.history_filter_date_to = st.date_input(
                "Date To:",
                value=st.session_state.history_filter_date_to, # Use state
                key="hist_filter_date_to_input"
            )

        # --- Load/Refresh Button ---
        if st.button("🔄 Load / Refresh Meeting History", key="load_history_filtered", use_container_width=True):
            # Reset analysis state when reloading meetings
            st.session_state.selected_meeting_id_history = None
            if "history_meeting_select" in st.session_state: st.session_state.history_meeting_select = "-- Select a Meeting --"
            if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']
            st.session_state.analysis_results_offset = 0
            st.session_state.analysis_results_total_count = 0

            with st.spinner("Loading meetings..."):
                # Prepare filter params for API call
                meeting_params = {'limit': 500} # Still load a good chunk for dropdown, pagination for meetings isn't implemented here yet
                if st.session_state.history_filter_title:
                    meeting_params['title'] = st.session_state.history_filter_title
                if st.session_state.history_filter_date_from:
                    # Format date for API query param (assuming API expects YYYY-MM-DD)
                    meeting_params['date_from'] = st.session_state.history_filter_date_from.isoformat()
                if st.session_state.history_filter_date_to:
                    meeting_params['date_to'] = st.session_state.history_filter_date_to.isoformat()

                meetings = make_request("GET", "/meetings/", params=meeting_params)
                if isinstance(meetings, list):
                    st.session_state.history_meetings_list = meetings
                    st.success(f"Loaded {len(meetings)} meetings matching filters.")
                    if not meetings: st.info("No meetings found matching filters.")
                else:
                    st.session_state.history_meetings_list = []
                    st.warning("Could not load meetings history.")

        # --- Meeting Selection Dropdown ---
        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list:
             # This logic remains mostly the same, using the potentially filtered list
             meetings_list = st.session_state.history_meetings_list
             try: sorted_meetings = sorted(meetings_list, key=lambda m: m.get('meeting_date',''), reverse=True)
             except: sorted_meetings = meetings_list

             meeting_options = {"-- Select a Meeting --": None}
             for m in sorted_meetings:
                 m_id=m.get('id'); m_title=m.get('title','Untitled'); m_date_str=m.get('meeting_date','')
                 try: m_date_fmt = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                 except: m_date_fmt = m_date_str
                 label = f"{m_title} (ID: {m_id} | {m_date_fmt})"
                 meeting_options[label] = m_id

             meeting_options_list = list(meeting_options.keys())
             selected_id_from_state = st.session_state.get('selected_meeting_id_history')
             current_index = 0
             if selected_id_from_state:
                 try:
                     selected_label = next(label for label, id_val in meeting_options.items() if id_val == selected_id_from_state)
                     current_index = meeting_options_list.index(selected_label)
                 except (StopIteration, ValueError):
                     # If previously selected meeting is filtered out, reset
                     st.session_state.selected_meeting_id_history = None

             selected_meeting_label = st.selectbox(
                 "Select Meeting to View Analysis", options=meeting_options_list, index=current_index, key="history_meeting_select")

             current_selected_meeting_id = meeting_options.get(selected_meeting_label)

             # --- Reset analysis pagination if meeting selection changes ---
             if st.session_state.get('selected_meeting_id_history') != current_selected_meeting_id:
                 st.session_state.analysis_results_offset = 0
                 st.session_state.analysis_results_total_count = 0
                 if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']
                 if '_cached_analysis_meeting_id' in st.session_state: del st.session_state['_cached_analysis_meeting_id']

             st.session_state.selected_meeting_id_history = current_selected_meeting_id

             # --- Display Analysis if a Meeting is Selected ---
             if current_selected_meeting_id:
                 st.divider()
                 # --- Delete Button Logic (Unchanged) ---
                 del_col, title_col = st.columns([1,5])
                 with title_col: st.subheader(f"Analysis Results for: {selected_meeting_label}")
                 with del_col:
                     # ... (keep existing delete logic) ...
                     delete_button_key = f"delete_init_{current_selected_meeting_id}"
                     confirm_delete_key = f"confirm_delete_{current_selected_meeting_id}"
                     if st.button("🗑️ Del", key=delete_button_key, help="Delete Meeting", use_container_width=True): st.session_state[confirm_delete_key] = True; st.rerun()
                     if st.session_state.get(confirm_delete_key, False):
                         st.warning(f"Confirm Deletion: '{selected_meeting_label}'?"); c1, c2 = st.columns(2)
                         if c1.button("✅ Yes", key=f"del_ok_{current_selected_meeting_id}", type="primary", use_container_width=True):
                             with st.spinner("Deleting..."): del_resp = make_request("DELETE", f"/meetings/{current_selected_meeting_id}/")
                             if del_resp is True:
                                 st.success("Deleted."); st.session_state.history_meetings_list = [m for m in st.session_state.history_meetings_list if m.get('id') != current_selected_meeting_id]
                                 logout(silent=True) # Partial logout to clear history state is safer
                                 st.session_state.logged_in = True # Keep logged in
                                 st.session_state.selected_meeting_id_history = None # Ensure deselection
                                 st.rerun()
                             else: st.error("Deletion failed."); del st.session_state[confirm_delete_key]; st.rerun()
                         if c2.button("❌ No", key=f"del_no_{current_selected_meeting_id}", use_container_width=True): del st.session_state[confirm_delete_key]; st.rerun()

                 # --- Fetch and Display Paginated Analysis Results ---
                 if not st.session_state.get(confirm_delete_key, False):
                     cached_meeting_id = st.session_state.get('_cached_analysis_meeting_id')
                     # Fetch only if meeting changed OR analysis data isn't cached for this meeting
                     # Note: Rerunning due to pagination button click will also trigger fetch if cache logic isn't perfect
                     if cached_meeting_id != current_selected_meeting_id or 'selected_meeting_analyses' not in st.session_state:
                         analysis_endpoint = f"/analysis/meeting/{current_selected_meeting_id}/"
                         analysis_params = {
                             'offset': st.session_state.analysis_results_offset,
                             'limit': st.session_state.analysis_results_limit
                         }
                         with st.spinner(f"Fetching analysis page {st.session_state.analysis_results_offset // st.session_state.analysis_results_limit + 1}..."):
                             analysis_response = make_request("GET", analysis_endpoint, params=analysis_params)

                             results_list = []
                             if isinstance(analysis_response, dict) and 'items' in analysis_response: # Expected Paginated Response
                                 results_list = analysis_response['items']
                                 st.session_state.analysis_results_total_count = analysis_response['count']
                                 # Update offset/limit based on response? Usually not needed as we sent them.
                             elif analysis_response is not None: # Unexpected format
                                 st.warning(f"Could not load analysis results. Unexpected format.")

                             st.session_state.selected_meeting_analyses = results_list
                             st.session_state._cached_analysis_meeting_id = current_selected_meeting_id # Cache for this meeting ID
                             if not results_list and analysis_response is not None:
                                 st.info("No analysis results found for this meeting.")

                     # --- Display Current Page of Analysis Results ---
                     if 'selected_meeting_analyses' in st.session_state and st.session_state.selected_meeting_analyses:
                         sorted_analyses = st.session_state.selected_meeting_analyses # Already sorted by API? or sort here if needed
                         meeting_participants = None
                         try: meeting_details = next(m for m in st.session_state.history_meetings_list if m.get('id') == current_selected_meeting_id); meeting_participants = meeting_details.get('participants')
                         except StopIteration: pass

                         st.write(f"Displaying {len(sorted_analyses)} analysis result(s):")
                         for analysis_result in sorted_analyses:
                             # ... (display logic using display_analysis_results remains the same) ...
                             transcript_id = analysis_result.get('transcript_id', 'N/A'); created_time_str = analysis_result.get('created_at', 'N/A')
                             try: created_time_fmt = datetime.fromisoformat(created_time_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M') if created_time_str != 'N/A' else 'N/A'
                             except: created_time_fmt = created_time_str
                             expander_label = f"Analysis for Transcript ID: {transcript_id} (Created: {created_time_fmt})"
                             with st.expander(expander_label, expanded=True):
                                 display_analysis_results(analysis_result, participants=meeting_participants, transcript_title=None, include_json_expander=False)
                                 if st.checkbox("Show Raw JSON", key=f"json_check_{transcript_id}_{created_time_str}", value=False): st.json(analysis_result)
                             st.markdown("---", unsafe_allow_html=True)

                         # --- Analysis Results Pagination Controls ---
                         total_results = st.session_state.analysis_results_total_count
                         limit = st.session_state.analysis_results_limit
                         current_offset = st.session_state.analysis_results_offset
                         total_pages = math.ceil(total_results / limit)
                         current_page = (current_offset // limit) + 1

                         if total_pages > 1: # Only show pagination if needed
                             st.write("---")
                             nav_cols = st.columns([1, 2, 1])
                             with nav_cols[0]: # Previous Button
                                 if st.button("⬅️ Previous", key="prev_analysis", disabled=(current_page <= 1)):
                                     st.session_state.analysis_results_offset = max(0, current_offset - limit)
                                     st.rerun() # Rerun to fetch previous page
                             with nav_cols[1]: # Page Indicator
                                 st.markdown(f"<div style='text-align: center;'>Page {current_page} of {total_pages} ({total_results} results)</div>", unsafe_allow_html=True)
                             with nav_cols[2]: # Next Button
                                 if st.button("Next ➡️", key="next_analysis", disabled=(current_page >= total_pages)):
                                     st.session_state.analysis_results_offset = current_offset + limit
                                     st.rerun() # Rerun to fetch next page

                     elif 'selected_meeting_analyses' in st.session_state:
                          pass # "No analysis results" message shown during fetch if list is empty

        elif 'history_meetings_list' in st.session_state and not st.session_state.history_meetings_list:
             st.info("No meetings loaded. Use the button above.")
        # else: # No meetings loaded yet, don't show anything below load button

# --- Footer or Initial Message (If Not Logged In) ---
elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar.")