import streamlit as st
import requests
import json
from datetime import datetime, timedelta

st.set_page_config(layout="wide")

API_BASE_URL = st.sidebar.text_input("API Base URL", "http://127.0.0.1:8000/api")

def login(username, password):
    try:
        response = requests.post(
            f"{API_BASE_URL}/token/pair",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.refresh_token = token_data["refresh"]
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4)
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
        st.session_state.token_expiry = datetime.now() + timedelta(minutes=4)
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Your session may have expired. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        logout()
        return False

def verify_token():
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
    keys_to_remove = [
        'access_token', 'refresh_token', 'token_expiry', 'username',
        'history_meetings_list', 'selected_meeting_id_history',
        'selected_meeting_analyses'
    ]
    for key in keys_to_remove:
        if key in st.session_state:
            del st.session_state[key]
    st.success("Logged out.")


def ensure_authenticated():
    if 'access_token' not in st.session_state:
        return False
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=30)):
        if not refresh_token():
            return False
    return True


def get_headers(include_content_type=True):
    if 'access_token' not in st.session_state:
         st.error("Authentication token missing unexpectedly.")
         st.stop()
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def make_request(method, endpoint, json_data=None, data=None, files=None, **kwargs):

    if not ensure_authenticated():
        return None

    include_content_type = not files and not data
    headers = get_headers(include_content_type=include_content_type)
    url = f"{API_BASE_URL}{endpoint}"

    try:
        response = requests.request(method, url, headers=headers, json=json_data, data=data, files=files, **kwargs)

        if response.status_code == 401:
            st.warning("Received 401 Unauthorized. Attempting token refresh...")
            if refresh_token():
                headers = get_headers(include_content_type=include_content_type)
                st.info("Retrying request with new token...")
                response = requests.request(method, url, headers=headers, json=json_data, data=data, files=files, **kwargs)
                if response.status_code == 401:
                    st.error("Authentication still failed after token refresh. Please log in again.")
                    logout()
                    return None
            else:
                st.error("Token refresh failed. Please log in again.")
                return None

        response.raise_for_status()

        if response.status_code == 204:
            return True
        elif response.text:
            try:
                return response.json()
            except json.JSONDecodeError:
                st.warning(f"Response status {response.status_code} OK, but content is not valid JSON.")
                st.text(response.text[:500] + "...")
                return response.text
        else:
            return True

    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP Error: {http_err}")
        if http_err.response is not None:
            st.error(f"Status Code: {http_err.response.status_code}")
            try:
                error_detail = http_err.response.json()
                detail_msg = error_detail.get('detail', json.dumps(error_detail))
                st.error(f"API Error Detail: {detail_msg}")
            except json.JSONDecodeError:
                st.text(http_err.response.text)
        return None
    except requests.exceptions.RequestException as req_err:
        st.error(f"Request Failed: {req_err}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred in make_request: {e}")
        return None

def display_analysis_results(result, include_json_expander=True):
    if not isinstance(result, dict):
        st.warning("Invalid analysis result format.")
        return

    st.markdown(f"**Transcript ID:** `{result.get('transcript_id', 'N/A')}`")

    col_summary, col_details = st.columns([2, 1])

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
        deadline = result.get('deadline')

        if task or responsible or deadline:
             st.markdown(f"**Task:** {task if task else '_Not specified_'}")
             st.markdown(f"**Responsible:** {responsible if responsible else '_Not specified_'}")
             st.markdown(f"**Deadline:** {deadline if deadline else '_Not specified_'}")
        else:
             st.info("No specific action item extracted.")

        created_at_str = result.get('created_at')
        updated_at_str = result.get('updated_at')
        if created_at_str: st.caption(f"Created: {created_at_str}")
        if updated_at_str: st.caption(f"Updated: {updated_at_str}")

    if include_json_expander:
        with st.expander("🔍 View Raw JSON Response"):
            st.json(result)

st.title("Meeting Analysis")

with st.sidebar:
    st.subheader("Authentication")
    if 'access_token' in st.session_state:
        st.success(f"Logged in as {st.session_state.get('username', 'User')}")
        if 'token_expiry' in st.session_state:
             try:
                 remaining = st.session_state.token_expiry - datetime.now()
                 if remaining.total_seconds() > 0:
                     remaining_mins = max(0, int(remaining.total_seconds() / 60))
                     remaining_secs = max(0, int(remaining.total_seconds() % 60))
                     st.info(f"Token expires in: {remaining_mins}m {remaining_secs}s")
                 else:
                     st.warning("Access token has expired.")
             except Exception:
                 st.warning("Could not determine token expiry.")
        if st.button("Logout"):
            logout()
            st.rerun()
    else:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Login")
            if submitted:
                if login(username, password):
                    st.session_state.username = username
                    st.success("Login successful!")
                    st.rerun()

if ensure_authenticated():

    tab_analysis, tab_history = st.tabs(["✨ Analysis", "📂 History"])

    with tab_analysis:
        st.header("Submit New Transcript for Analysis")
        st.info("Submit transcript text or file. The system will create the meeting, transcript, analyze it, and show the results.")
        with st.form("direct_submit_form"):
            input_method = st.radio("Input Method", ["Paste Text", "Upload File"], index=0, key="direct_input_method")
            raw_text_input = None
            uploaded_file_input = None
            if input_method == "Paste Text":
                raw_text_input = st.text_area("Paste Raw Transcript Text Here", height=300, key="direct_raw_text")
            else:
                uploaded_file_input = st.file_uploader("Choose a transcript file (.txt, .vtt, etc.)", type=['txt', 'vtt', 'srt'], key="direct_file_upload")
            submitted_direct = st.form_submit_button("🚀 Submit and Analyze")

            if submitted_direct:
                endpoint = "/analysis/process/direct/"
                form_data = None
                files_payload = None
                has_input = False

                if input_method == "Paste Text":
                    if raw_text_input and raw_text_input.strip():
                        form_data = {'raw_text': raw_text_input}
                        st.write("Submitting raw text...")
                        has_input = True
                    else:
                        st.warning("Please paste some transcript text.")
                elif input_method == "Upload File":
                    if uploaded_file_input is not None:
                        files_payload = {'file': (uploaded_file_input.name, uploaded_file_input, uploaded_file_input.type)}
                        st.write(f"Submitting file: {uploaded_file_input.name}")
                        has_input = True
                    else:
                        st.warning("Please upload a transcript file.")

                if has_input:
                    with st.spinner("Processing transcript and generating analysis... This may take a minute."):
                        result = make_request("POST", endpoint, data=form_data, files=files_payload)

                        if isinstance(result, dict):
                            st.success("✅ Processing Complete!")
                            st.divider()
                            st.subheader("📊 Analysis Results")
                            display_analysis_results(result)
                            if 'history_meetings_list' in st.session_state:
                                del st.session_state['history_meetings_list']
                            if 'selected_meeting_analyses' in st.session_state:
                                del st.session_state['selected_meeting_analyses']
                        elif result is None:
                             st.error("❌ Processing failed. Check error messages above or API logs for details.")
                        else:
                             st.error("❌ Processing failed. Unexpected response format received from API.")
                             st.text(result)
    with tab_history:
        st.header("View Past Analysis Results")

        if st.button("🔄 Load Meeting History", key="load_history"):
            with st.spinner("Loading meetings..."):
                meetings = make_request("GET", "/meetings/?limit=500")

                if isinstance(meetings, list):
                    st.session_state.history_meetings_list = meetings
                    st.success(f"Loaded {len(meetings)} meetings.")
                    if not meetings:
                        st.info("No past meetings found.")
                    if 'selected_meeting_analyses' in st.session_state:
                        del st.session_state['selected_meeting_analyses']
                    if '_cached_analysis_meeting_id' in st.session_state:
                        del st.session_state['_cached_analysis_meeting_id']

                else:
                    st.session_state.history_meetings_list = []
                    st.warning("Could not load meetings history.")

        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list:
            meetings_list = st.session_state.history_meetings_list
            try:
                sorted_meetings = sorted(
                    meetings_list,
                    key=lambda m: m.get('meeting_date', m.get('created_at', '1970-01-01T00:00:00Z')),
                    reverse=True
                )
            except Exception as sort_e:
                st.warning(f"Could not sort meetings by date: {sort_e}")
                sorted_meetings = meetings_list
            meeting_options = {
                f"{m.get('title', 'Untitled')} (ID: {m.get('id', 'N/A')} | Date: {m.get('meeting_date', 'N/A')[:16]})": m.get(
                    'id')
                for m in sorted_meetings
            }
            meeting_options_list = ["-- Select a Meeting --"] + list(meeting_options.keys())
            options_keys = list(meeting_options.keys())
            selected_id_from_state = st.session_state.get('selected_meeting_id_history')
            current_index = 0
            if selected_id_from_state:
                try:
                    selected_label = next(
                        label for label, id_val in meeting_options.items() if id_val == selected_id_from_state)
                    current_index = meeting_options_list.index(selected_label)
                except (StopIteration, ValueError):
                    current_index = 0

            selected_meeting_label = st.selectbox(
                "Select Meeting to View Analysis",
                options=meeting_options_list,
                index=current_index,
                key="history_meeting_select"
            )

            selected_meeting_id = None
            if selected_meeting_label != "-- Select a Meeting --":
                selected_meeting_id = meeting_options.get(selected_meeting_label)

            st.session_state.selected_meeting_id_history = selected_meeting_id
            if selected_meeting_id:
                st.divider()
                st.subheader(f"Analysis Results for: {selected_meeting_label}")

                cached_id = st.session_state.get('_cached_analysis_meeting_id')
                analyses_in_state = 'selected_meeting_analyses' in st.session_state

                if not analyses_in_state or cached_id != selected_meeting_id:
                    endpoint = f"/analysis/meeting/{selected_meeting_id}/"
                    with st.spinner(f"Fetching analysis results for meeting ID {selected_meeting_id}..."):
                        analysis_results_list = make_request("GET", endpoint)

                        if isinstance(analysis_results_list, list):
                            st.session_state.selected_meeting_analyses = analysis_results_list
                            st.session_state._cached_analysis_meeting_id = selected_meeting_id
                            if not analysis_results_list:
                                st.info("No analysis results found for this meeting.")
                        else:
                            st.warning(f"Could not load analysis results for meeting {selected_meeting_id}.")
                            st.session_state.selected_meeting_analyses = []
                            st.session_state._cached_analysis_meeting_id = selected_meeting_id

                if 'selected_meeting_analyses' in st.session_state and st.session_state.selected_meeting_analyses:
                    for analysis_result in st.session_state.selected_meeting_analyses:
                        transcript_id = analysis_result.get('transcript_id', 'N/A')
                        created_time = analysis_result.get('created_at', datetime.now().isoformat())[
                                       :16]
                        expander_label = f"Analysis for Transcript ID: {transcript_id} (Created: {created_time})"

                        with st.expander(expander_label, expanded=True):
                            display_analysis_results(analysis_result, include_json_expander=False)
                            button_key = f"json_{transcript_id}_{created_time}"  # Unique key
                            if st.button("Show Raw JSON", key=button_key):
                                st.json(analysis_result)
                        st.markdown("---")

                elif 'selected_meeting_analyses' in st.session_state and not st.session_state.selected_meeting_analyses:
                    pass
        elif 'history_meetings_list' in st.session_state and not st.session_state.history_meetings_list:
            st.info("No past meetings found in history.")
        else:
            st.info("Click 'Load Meeting History' button above to view past analyses.")

elif 'access_token' not in st.session_state:
    st.info("👋 Welcome! Please log in using the sidebar to access the application features.")