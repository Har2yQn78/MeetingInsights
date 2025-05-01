import streamlit as st
import requests
import json
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Any
import io
import math
import traceback

st.set_page_config(layout="wide", page_title="Meeting Analysis & Q&A")

with st.sidebar:
    st.subheader("API Configuration")
    if "api_base_url" not in st.session_state:
        st.session_state.api_base_url = "http://127.0.0.1:8000/api"
    st.text_input("API Base URL", key="api_base_url")

def login(username, password):
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    try:
        response = requests.post(f"{api_base}/token/pair", json={"username": username, "password": password})
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.refresh_token = token_data["refresh"]
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55)
        st.session_state.logged_in = True
        st.session_state.username = username
        st.success("Login successful!")
        st.rerun()
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {e}")
        if hasattr(e, 'response') and e.response:
            try:
                err = e.response.json().get("detail", "Unknown error")
                st.error(f"API Error: {err}")
            except json.JSONDecodeError:
                st.error(f"API Error: Status {e.response.status_code} - {e.response.text[:200]}...")
        logout(silent=True)
        return False

def refresh_token():
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    if 'refresh_token' not in st.session_state:
        logout(silent=True)
        return False
    try:
        response = requests.post(f"{api_base}/token/refresh", json={"refresh": st.session_state.refresh_token})
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55)
        st.session_state.logged_in = True
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Session expired or refresh failed.")
        if hasattr(e, 'response') and e.response and e.response.status_code in [401, 400]:
            st.error("Reason: Refresh token may be invalid or expired.")
        else:
            st.error(f"Refresh failed: {e}")
        logout()
        return False

def logout(silent=False):
    if not silent:
        st.info("Logging out...")
    keys_to_remove = [k for k in st.session_state if k != "api_base_url"]
    for key in keys_to_remove:
        try:
            del st.session_state[key]
        except KeyError:
            pass
    if not silent:
        st.success("Logged out.")
        st.rerun()

def ensure_authenticated():
    if not st.session_state.get('logged_in', False) or 'access_token' not in st.session_state:
        return False
    buffer_seconds = 60
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=buffer_seconds)):
        if not refresh_token():
            return False
    return True

def get_headers(include_content_type=True):
    if 'access_token' not in st.session_state:
        st.error("Authentication token missing. Please log in.")
        return None

    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers

def make_request(method, endpoint, json_data=None, data=None, files=None, params=None, timeout=30, suppress_errors=False, **kwargs):
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    if not st.session_state.get('logged_in', False):
        if not suppress_errors:
            st.warning("Not logged in. Please log in first.")
        return None
    if not ensure_authenticated():
        if not suppress_errors:
            st.warning("Authentication failed or expired. Please log in.")
        return None
    include_content_type_header = json_data is not None and not files and not data
    headers = get_headers(include_content_type=include_content_type_header)
    if headers is None: return None
    req_params = params if params is not None else {}
    if method.upper() == 'GET' and json_data:
        req_params.update(json_data)
        json_data = None

    url = f"{api_base}{endpoint}"
    attempt_refresh = True

    try:
        response = requests.request(
            method, url, headers=headers, json=json_data, data=data,
            files=files, params=req_params, timeout=timeout, **kwargs
        )

        if response.status_code == 401 and attempt_refresh:
            st.warning("Token may have expired. Attempting refresh...")
            refreshed = refresh_token()
            if refreshed:
                st.info("Token refreshed successfully. Retrying request...")
                headers = get_headers(include_content_type=include_content_type_header)
                if headers:
                    response = requests.request(
                        method, url, headers=headers, json=json_data, data=data,
                        files=files, params=req_params, timeout=timeout, **kwargs
                    )
                    if response.status_code == 401:
                         if not suppress_errors: st.error("Authentication failed even after token refresh.")
                         logout()
                         return None
                else:
                     if not suppress_errors: st.error("Failed to get headers after token refresh.")
                     return None
            else:
                return None
        response.raise_for_status()

        # Handle successful responses
        if response.status_code == 204: return True
        elif response.status_code in [200, 201, 202]:
            if response.text:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    if not suppress_errors: st.warning(f"API returned non-JSON response (Status: {response.status_code}).")
                    return response.text
            else:
                return True
        else:
            if not suppress_errors: st.warning(f"Unexpected success status code: {response.status_code}")
            return response.text if response.text else True

    except requests.exceptions.HTTPError as e:
        if e.response is not None:
            status_code = e.response.status_code
            if status_code == 401:
                if not suppress_errors: st.error(f"Authentication error (Status: {status_code}). Please log in again.")
                logout()
            elif status_code == 403:
                if not suppress_errors: st.error(f"Permission Denied (Status: {status_code}). You may not have access to this resource.")
            elif status_code == 404:
                 if not suppress_errors: st.error(f"Resource Not Found (Status: {status_code}) at {url}.")
            else:
                if not suppress_errors:
                    st.error(f"HTTP Error: {e} (Status: {status_code})")
                    try:
                        err_data = e.response.json()
                        detail = err_data.get('detail', json.dumps(err_data))
                        if isinstance(detail, list): detail = "; ".join(map(str, detail))
                        elif not isinstance(detail, str): detail = json.dumps(detail)
                        st.error(f"API Detail: {detail}")
                    except json.JSONDecodeError:
                        st.error(f"Raw Error Response: {e.response.text[:500]}...")
        else:
             if not suppress_errors: st.error(f"HTTP Error: {e}")
        return None
    except requests.exceptions.ConnectionError as e:
        if not suppress_errors: st.error(f"Connection Error: Could not connect to API at {api_base}. Details: {e}")
        return None
    except requests.exceptions.Timeout as e:
        if not suppress_errors: st.error(f"Request Timeout: The API did not respond within {timeout} seconds. Details: {e}")
        return None
    except requests.exceptions.RequestException as e:
        if not suppress_errors: st.error(f"Request Failed: An unexpected request error occurred. Details: {e}")
        return None
    except Exception as e:
        if not suppress_errors:
             st.error(f"An unexpected error occurred in make_request: {type(e).__name__} - {e}")
             st.error(traceback.format_exc())
        return None

def display_analysis_results(result, participants: Optional[List[Any]] = None, include_json_expander=True):
    if not isinstance(result, dict):
        st.warning("Invalid analysis result format received.")
        st.json(result)
        return

    tx_id = result.get('transcript_id', 'N/A')
    tx_title = result.get('transcript_title')
    title_str = f"**Transcript ID:** `{tx_id}`"
    if tx_title:
        title_str += f" | **Title:** *{tx_title}*"
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(title_str)
        st.subheader("📝 Summary")
        st.markdown(result.get('summary') or "_No summary provided._")
        st.subheader("📌 Key Points")
        key_points = result.get('key_points')
        if key_points and isinstance(key_points, list):
            st.markdown("\n".join(f"- {p}" for p in key_points))
        else:
            st.markdown("_No key points extracted._")

    with col2:
        st.subheader("❗ Action Items")
        task = result.get('task')
        responsible = result.get('responsible')
        deadline = result.get('deadline')

        if task or responsible or deadline:
             st.markdown(f"**Task:** {task or '_N/A_'}")
             st.markdown(f"**Responsible:** {responsible or '_N/A_'}")
             deadline_str = deadline
             if deadline:
                 try:
                     if isinstance(deadline, str):
                        deadline = deadline.replace('Z', '+00:00')
                        if 'T' in deadline:
                           deadline_dt = datetime.fromisoformat(deadline).date()
                        else:
                           deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").date()
                        deadline_str = deadline_dt.strftime("%B %d, %Y")
                     elif isinstance(deadline, date):
                        deadline_str = deadline.strftime("%B %d, %Y")
                     # Add other type checks if necessary
                 except (ValueError, TypeError) as e:
                     st.warning(f"Could not parse deadline format: {deadline} ({type(deadline)}). Error: {e}")
                     deadline_str = str(deadline)
             st.markdown(f"**Deadline:** {deadline_str or '_N/A_'}")
        else:
            st.info("No action items identified.")

        st.subheader("👥 Participants")
        st.markdown(f"{', '.join(map(str, participants))}" if participants else "_N/A_")

        st.caption("---")
        ts_created = result.get('created_at')
        ts_updated = result.get('updated_at')
        dt_created, dt_updated = None, None
        try:
            if ts_created:
                dt_created = datetime.fromisoformat(str(ts_created).replace('Z','+00:00'))
                st.caption(f"Analyzed: {dt_created.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            if ts_updated:
                dt_updated = datetime.fromisoformat(str(ts_updated).replace('Z','+00:00'))
                if dt_created is None or abs((dt_updated - dt_created).total_seconds()) > 5:
                    st.caption(f"Updated: {dt_updated.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except Exception as e:
            st.warning(f"Timestamp parsing error: {e}")

    if include_json_expander:
        with st.expander("🔍 View Raw JSON (Analysis Result)"):
            st.json(result)

def display_chatbot_interface(transcript_id):
    st.divider()
    st.subheader(f"💬 Ask a Question about Transcript `{transcript_id}`")
    chat_base_key = f"chat_{transcript_id}"
    qa_form_key = f"{chat_base_key}_form"
    qa_input_key = f"{chat_base_key}_input"
    if chat_base_key not in st.session_state:
        st.session_state[chat_base_key] = {"history": []}
    with st.form(qa_form_key, clear_on_submit=True):
        user_question = st.text_input("Your Question:", key=qa_input_key, label_visibility="collapsed", placeholder="Ask something about the transcript...")
        submit_qa = st.form_submit_button("Ask")

        if submit_qa and user_question:
            with st.spinner("Thinking..."):
                qa_payload = {"question": user_question}
                answer_resp = make_request("POST", f"/chatbot/ask/{transcript_id}/", json_data=qa_payload, timeout=90)

                qa_result = {"q": user_question}
                if isinstance(answer_resp, dict) and 'answer' in answer_resp:
                    qa_result["a"] = answer_resp['answer']
                else:
                     error_detail = "Failed to get an answer from the API."
                     if answer_resp is None and not ensure_authenticated():
                         error_detail = "Authentication error. Please log in again."
                     elif isinstance(answer_resp, str):
                         error_detail = f"API Error: {answer_resp}"

                     qa_result["e"] = error_detail
                st.session_state[chat_base_key]["history"].insert(0, qa_result)
            st.rerun()
    chat_history = st.session_state[chat_base_key]["history"]
    if chat_history:
        st.markdown("**Chat History:**")
        with st.container(height=400):
            for item in chat_history:
                st.markdown(f"> **Q:** {item['q']}")
                if item.get('a'):
                    st.info(f"{item['a']}")
                elif item.get('e'):
                    st.error(f"**Error:** {item['e']}")
                st.caption(f"_{datetime.now().strftime('%H:%M:%S')}_")
                st.markdown("---")
st.title("🗣️ Meeting Analysis & Q&A")
with st.sidebar:
    st.subheader("Authentication")
    if st.session_state.get('logged_in', False):
        st.success(f"Logged in as: **{st.session_state.get('username', 'User')}**")
        if 'token_expiry' in st.session_state:
            try:
                remaining_time = st.session_state.token_expiry - datetime.now()
                if remaining_time.total_seconds() > 0:
                    mins = int(remaining_time.total_seconds() // 60)
                    secs = int(remaining_time.total_seconds() % 60)
                    st.caption(f"Session valid for approx. {mins} min {secs} sec")
                else:
                    st.caption("Session expired. Refreshing...")
                    ensure_authenticated()
            except Exception as e:
                st.caption(f"Error checking token expiry: {e}")
        if st.button("Logout", key="logout_button", type="primary"):
            logout()
    else:
        with st.form("login_form"):
            st.markdown("Please log in")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            login_submitted = st.form_submit_button("Login")
            if login_submitted:
                login(username, password)

if st.session_state.get('logged_in', False):
    default_session_keys = {
        'meeting_action_radio': "Select Existing Meeting",
        'select_meeting_dropdown_analysis': "-- Select --",
        'analysis_tab_meetings_list': None,
        'current_analysis_job': None,
        'current_analysis_result': None,
        'current_qna_status': None,
        'history_filter_title': "",
        'history_filter_date_from': None,
        'history_filter_date_to': None,
        'history_meetings_list': None,
        'history_meeting_select': "-- Select --",
        'selected_meeting_id_history': None,
        'selected_meeting_analyses': None,
        'history_confirm_delete': None,
        'qanda_meetings_list': None,
        'qanda_meeting_select': "-- Select --",
        'qanda_selected_meeting_id': None,
        'qanda_available_transcripts': None,
        'qanda_transcript_select': "-- Select --",
        'qanda_selected_transcript_id': None,
        'qanda_selected_transcript_status': None,
    }
    for key, default in default_session_keys.items():
        if key not in st.session_state:
            st.session_state[key] = default
    just_created_meeting_id = st.session_state.pop('just_created_meeting_id', None)
    if just_created_meeting_id:
        st.session_state.meeting_action_radio = "Select Existing Meeting"
        st.session_state.analysis_tab_meetings_list = None
        st.session_state.history_meetings_list = None
        st.session_state.qanda_meetings_list = None
        st.success(f"Meeting ID {just_created_meeting_id} created. You can now select it.")

    tab_analysis, tab_history, tab_qanda = st.tabs(["✨ New Analysis", "📂 History", "💬 Q&A"])
    with tab_analysis:
        st.header("Submit New Transcript for Analysis")
        st.subheader("Step 1: Select or Create Meeting")
        col1_meeting, col2_meeting = st.columns(2)
        with col1_meeting:
            st.radio(
                "Choose Action:",
                ["Select Existing Meeting", "Create New Meeting"],
                key="meeting_action_radio",
                horizontal=True,
                label_visibility="collapsed"
            )

        selected_meeting_id_analysis = None
        selected_meeting_title_analysis = None
        if st.session_state.meeting_action_radio == "Select Existing Meeting":
            with col2_meeting:
                if st.session_state.analysis_tab_meetings_list is None:
                    with st.spinner("Loading meetings..."):
                        meetings = make_request("GET","/meetings/", params={"limit": 500, "ordering": "-meeting_date"})
                        if isinstance(meetings, list):
                            st.session_state.analysis_tab_meetings_list = meetings
                        else:
                            st.session_state.analysis_tab_meetings_list = []

                meetings_list = st.session_state.analysis_tab_meetings_list
                if meetings_list:
                    meeting_options = {"-- Select --": None}
                    for m in meetings_list:
                        m_id, m_title, m_date_str = m.get('id'), m.get('title', 'Untitled'), m.get('meeting_date', '')
                        try: m_date_formatted = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                        except: m_date_formatted = m_date_str if m_date_str else "Invalid Date"
                        label = f"{m_title} ({m_date_formatted}) - ID:{m_id}"
                        meeting_options[label] = m_id

                    selected_label = st.selectbox("Select Meeting:", options=list(meeting_options.keys()),
                                                  key="select_meeting_dropdown_analysis", label_visibility="collapsed")
                    selected_meeting_id_analysis = meeting_options.get(selected_label)
                    if selected_meeting_id_analysis:
                        selected_meeting_title_analysis = selected_label.split(" (")[0]
                elif isinstance(meetings_list, list):
                    st.info("No meetings found. Create one below.")

        elif st.session_state.meeting_action_radio == "Create New Meeting":
             with col2_meeting:
                 with st.form("create_meeting_form"):
                    new_title = st.text_input("New Meeting Title*", key="new_meeting_title_input")
                    submitted_create = st.form_submit_button("Create Meeting")
                    if submitted_create:
                        if new_title.strip():
                            with st.spinner("Creating meeting..."):
                                create_payload = {"title": new_title.strip()}
                                response = make_request("POST", "/meetings/", json_data=create_payload)
                            if isinstance(response, dict) and 'id' in response:
                                st.session_state.just_created_meeting_id = response['id']
                                st.rerun()
                        else:
                            st.warning("Meeting title cannot be empty.")

        st.divider()
        if selected_meeting_id_analysis and not st.session_state.current_analysis_job:
            st.subheader(f"Step 2: Add Transcript to '{selected_meeting_title_analysis or f'Meeting ID:{selected_meeting_id_analysis}'}'")

            with st.form("transcript_submit_form", clear_on_submit=True):
                input_method = st.radio("Input Method:", ["Paste Text", "Upload File"], key="transcript_input_method", horizontal=True)
                transcript_text_input = None
                uploaded_file_input = None

                if input_method == "Paste Text":
                    transcript_text_input = st.text_area("Paste Transcript Text Here:", height=200, key="transcript_raw_text_input", placeholder="Paste the full meeting transcript here...")
                else:
                    uploaded_file_input = st.file_uploader("Upload Transcript File:", type=['txt', 'pdf', 'md', 'docx'], key="transcript_file_uploader")

                submit_transcript = st.form_submit_button("🚀 Submit for Analysis")

                if submit_transcript:
                    st.session_state.current_analysis_job = None
                    st.session_state.current_analysis_result = None
                    st.session_state.current_qna_status = None

                    api_endpoint, request_payload, request_files = None, None, None
                    if input_method == "Paste Text":
                        if transcript_text_input and transcript_text_input.strip():
                            api_endpoint = f"/transcripts/{selected_meeting_id_analysis}/"
                            request_payload = {'raw_text': transcript_text_input}
                        else:
                            st.warning("Pasted text cannot be empty.")
                    elif input_method == "Upload File":
                        if uploaded_file_input:
                            api_endpoint = f"/transcripts/{selected_meeting_id_analysis}/upload/"
                            file_content = uploaded_file_input.getvalue()
                            request_files = {'file': (uploaded_file_input.name, file_content, uploaded_file_input.type)}
                        else:
                            st.warning("Please upload a file.")

                    if api_endpoint and (request_payload or request_files):
                        with st.spinner("Submitting transcript... This may take a moment."):
                            submission_response = make_request("POST", api_endpoint, json_data=request_payload, files=request_files, timeout=120)

                        if isinstance(submission_response, dict) and 'id' in submission_response:
                            transcript_id = submission_response['id']
                            initial_status = submission_response.get('processing_status', 'PENDING')
                            st.success(f"✅ Transcript submitted (ID: {transcript_id}). Analysis queued.")
                            st.info(f"Initial Status: {initial_status}. Polling for updates...")
                            st.session_state.current_analysis_job = {
                                'transcript_id': transcript_id,
                                'status': initial_status,
                                'start_time': time.time(),
                                'meeting_id': selected_meeting_id_analysis
                            }
                            st.session_state.history_meetings_list = None
                            st.session_state.selected_meeting_analyses = None
                            st.session_state.qanda_meetings_list = None
                            st.session_state.qanda_available_transcripts = None
                            st.rerun()

        elif not selected_meeting_id_analysis and not st.session_state.current_analysis_job :
             st.info("Select or create a meeting above to submit a transcript.")
        if st.session_state.current_analysis_job:
            job = st.session_state.current_analysis_job
            transcript_id = job['transcript_id']
            current_status = job['status']
            MAX_POLL_TIME_SEC = 300
            POLLING_INTERVAL_SEC = 5

            analysis_status_placeholder = st.empty()
            qna_status_placeholder = st.empty()
            if current_status in ["PENDING", "PROCESSING"]:
                if time.time() - job.get('analysis_start_time', job['start_time']) > MAX_POLL_TIME_SEC:
                    st.warning(f"Analysis polling timed out after {MAX_POLL_TIME_SEC} seconds.")
                    job['status'] = "ANALYSIS_TIMED_OUT"
                    st.rerun()
                else:
                    with analysis_status_placeholder.container():
                        with st.spinner(f"Analyzing Transcript `{transcript_id}`... Status: {current_status}"):
                            status_response = make_request("GET", f"/transcripts/status/{transcript_id}/", suppress_errors=True)
                            if isinstance(status_response, dict) and 'processing_status' in status_response:
                                new_status = status_response['processing_status']
                            if new_status != current_status:
                                job['status'] = new_status
                                if new_status == "COMPLETED":
                                    st.info("Analysis complete. Fetching results...")
                                    analysis_result_response = make_request("GET", f"/analysis/transcript/{transcript_id}/")
                                    if isinstance(analysis_result_response, dict):
                                        st.session_state.current_analysis_result = analysis_result_response
                                        job['status'] = "CHECKING_QNA"
                                        job['qna_check_start_time'] = time.time()
                                    else:
                                        st.error("Analysis completed, but failed to fetch results.")
                                        job['status'] = "ANALYSIS_FAILED_POST"
                                elif new_status == "FAILED":
                                    error_msg = status_response.get('processing_error', 'Unknown error during analysis')
                                    st.error(f"Analysis Failed: {error_msg}")
                                    job['status'] = "ANALYSIS_FAILED"
                            time.sleep(POLLING_INTERVAL_SEC)
                            st.rerun()

            elif current_status == "CHECKING_QNA":
                qna_start_time = job.get('qna_check_start_time', job['start_time'])
                if time.time() - qna_start_time > MAX_POLL_TIME_SEC:
                     st.warning(f"Q&A status polling timed out after {MAX_POLL_TIME_SEC} seconds.")
                     job['status'] = "QNA_TIMED_OUT"
                     st.rerun()
                else:
                    with qna_status_placeholder.container():
                        with st.spinner(f"Preparing Q&A for Transcript `{transcript_id}`..."):
                            embed_stat_resp = make_request("GET", f"/chatbot/status/{transcript_id}/", suppress_errors=True)
                            qna_status = "PENDING"
                            if isinstance(embed_stat_resp, dict) and 'embedding_status' in embed_stat_resp:
                                qna_status = embed_stat_resp.get('embedding_status', 'Unknown')

                            st.session_state.current_qna_status = qna_status

                            if qna_status == "COMPLETED":
                                job['status'] = "QNA_READY"
                            elif qna_status == "FAILED":
                                job['status'] = "QNA_FAILED"
                            elif qna_status not in ["PENDING", "PROCESSING", "NONE"]:
                                st.warning(f"Unknown Q&A status received: {qna_status}. Treating as failure.")
                                job['status'] = "QNA_FAILED"
                            if job['status'] == "CHECKING_QNA":
                                time.sleep(POLLING_INTERVAL_SEC)
                                st.rerun()
                            else:
                                st.rerun()
            if st.session_state.current_analysis_result:
                 with analysis_status_placeholder.container():
                    st.success(f"📊 Analysis for Transcript `{transcript_id}` is complete.")
                    participants = None
                    try:
                        meeting_details = make_request("GET", f"/meetings/{job['meeting_id']}/", suppress_errors=True)
                        if isinstance(meeting_details, dict):
                            participants = meeting_details.get('participants')
                    except Exception: pass
                    display_analysis_results(st.session_state.current_analysis_result, participants=participants, include_json_expander=True)
            with qna_status_placeholder.container():
                if job['status'] == "QNA_READY":
                    st.success(f"✅ Q&A for Transcript `{transcript_id}` is ready!")
                    st.info("You can now ask questions about this transcript in the 'Q&A' tab.")
                elif job['status'] == "QNA_FAILED":
                    st.error(f"❌ Q&A preparation failed for Transcript `{transcript_id}`.")
                elif job['status'] == "QNA_TIMED_OUT":
                    st.warning(f"⏳ Q&A preparation timed out for Transcript `{transcript_id}`. Last known status: {st.session_state.current_qna_status or 'N/A'}")
                elif job['status'] in ["ANALYSIS_FAILED", "ANALYSIS_FAILED_POST"]:
                    st.error(f"❌ Analysis failed for Transcript `{transcript_id}`. Q&A not available.")
                elif job['status'] == "ANALYSIS_TIMED_OUT":
                     st.warning(f"⏳ Analysis processing timed out for Transcript `{transcript_id}`. Q&A not available.")
            terminal_states = ["QNA_READY", "QNA_FAILED", "QNA_TIMED_OUT",
                               "ANALYSIS_FAILED", "ANALYSIS_FAILED_POST", "ANALYSIS_TIMED_OUT"]
            if job['status'] in terminal_states:
                 if st.button("Analyze Another Transcript", key="clear_analysis_job"):
                     st.session_state.current_analysis_job = None
                     st.session_state.current_analysis_result = None
                     st.session_state.current_qna_status = None
                     st.rerun()

    with tab_history:
        st.header("View History")
        st.subheader("Filter Meetings")
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 1, 1, 1])
        with filter_col1: st.text_input("Filter by Title (contains):", key="history_filter_title")
        with filter_col2: st.date_input("Filter From Date:", key="history_filter_date_from", value=None)
        with filter_col3: st.date_input("Filter To Date:", key="history_filter_date_to", value=None)
        with filter_col4:
            st.write("")
            st.write("")
            if st.button("🔄 Load / Filter", key="load_history_button", use_container_width=True):
                st.session_state.selected_meeting_id_history = None
                st.session_state.history_meeting_select = "-- Select --"
                st.session_state.selected_meeting_analyses = None
                st.session_state.history_confirm_delete = None
                st.session_state.history_meetings_list = None
                st.rerun()
        if st.session_state.history_meetings_list is None:
             with st.spinner("Loading meetings..."):
                filter_params = {'limit': 500, 'ordering': '-meeting_date'}
                if st.session_state.history_filter_title:
                    filter_params['title__icontains'] = st.session_state.history_filter_title
                if st.session_state.history_filter_date_from:
                    filter_params['meeting_date__gte'] = st.session_state.history_filter_date_from.isoformat()
                if st.session_state.history_filter_date_to:
                    filter_params['meeting_date__lte'] = (st.session_state.history_filter_date_to + timedelta(days=1)).isoformat()

                meetings_data = make_request("GET", "/meetings/", params=filter_params)
                if isinstance(meetings_data, list):
                    st.session_state.history_meetings_list = meetings_data
                else:
                    st.session_state.history_meetings_list = []
        current_selected_meeting_id_hist = None
        meeting_options_hist = {"-- Select --": None}
        if isinstance(st.session_state.history_meetings_list, list) and st.session_state.history_meetings_list:
            meetings_list_hist = st.session_state.history_meetings_list
            # Create dropdown options
            for m in meetings_list_hist:
                m_id, m_title, m_date_str = m.get('id'), m.get('title', 'Untitled'), m.get('meeting_date', '')
                try:
                     m_date_formatted = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                except: m_date_formatted = m_date_str if m_date_str else "Invalid Date"
                label = f"{m_title} ({m_date_formatted}) - ID:{m_id}"
                meeting_options_hist[label] = m_id
            selected_label_hist = st.selectbox("Select Meeting to View:", options=list(meeting_options_hist.keys()), key="history_meeting_select")
            current_selected_meeting_id_hist = meeting_options_hist.get(selected_label_hist)
            if st.session_state.selected_meeting_id_history != current_selected_meeting_id_hist:
                 st.session_state.selected_meeting_id_history = current_selected_meeting_id_hist
                 st.session_state.selected_meeting_analyses = None
                 st.session_state.history_confirm_delete = None
                 st.rerun()

        elif isinstance(st.session_state.history_meetings_list, list) and not st.session_state.history_meetings_list:
             st.info("No meetings found matching the current filters.")

        if current_selected_meeting_id_hist:
            st.divider()
            if st.session_state.history_confirm_delete != current_selected_meeting_id_hist:
                header_col1, header_col2 = st.columns([4, 1])
                with header_col1:
                    selected_label_display = "-- Select --"
                    if current_selected_meeting_id_hist:
                        for label, m_id in meeting_options_hist.items():
                            if m_id == current_selected_meeting_id_hist:
                                selected_label_display = label
                                break
                        if selected_label_display == "-- Select --":
                             selected_label_display = f"Meeting ID: {current_selected_meeting_id_hist}"
                    st.subheader(f"Details for: {selected_label_display}")
                with header_col2:
                    delete_button_key = f"delete_meeting_{current_selected_meeting_id_hist}"
                    if st.button("🗑️ Delete", key=delete_button_key, help="Delete this meeting and all its data", type="secondary"):
                        st.session_state.history_confirm_delete = current_selected_meeting_id_hist
                        st.rerun()
            if st.session_state.history_confirm_delete == current_selected_meeting_id_hist:
                 st.error(f"**Confirm Deletion?** Meeting ID `{current_selected_meeting_id_hist}` and all related transcripts/analyses will be permanently lost.")
                 confirm_col1, confirm_col2 = st.columns(2)
                 with confirm_col1:
                     if st.button("✅ Yes, Delete Permanently", key=f"confirm_yes_{current_selected_meeting_id_hist}", type="primary"):
                         with st.spinner("Deleting meeting..."):
                            delete_resp = make_request("DELETE", f"/meetings/{current_selected_meeting_id_hist}/")
                         st.session_state.history_confirm_delete = None
                         if delete_resp is True:
                             st.success("Meeting deleted successfully.")
                             st.session_state.history_meetings_list = None
                             st.session_state.selected_meeting_id_history = None
                             st.session_state.history_meeting_select = "-- Select --"
                             st.session_state.selected_meeting_analyses = None
                             st.session_state.qanda_meetings_list = None
                             st.session_state.qanda_available_transcripts = None
                             st.rerun()
                         else:
                             st.rerun()
                 with confirm_col2:
                     if st.button("❌ No, Cancel", key=f"confirm_no_{current_selected_meeting_id_hist}"):
                         st.session_state.history_confirm_delete = None
                         st.rerun()
            if st.session_state.history_confirm_delete != current_selected_meeting_id_hist:
                 if st.session_state.selected_meeting_analyses is None:
                     with st.spinner(f"Fetching analyses for Meeting ID {current_selected_meeting_id_hist}..."):
                         analysis_endpoint = f"/analysis/meeting/{current_selected_meeting_id_hist}/"
                         analysis_response = make_request("GET", analysis_endpoint, params={"limit": 100})

                         results_list = []
                         if isinstance(analysis_response, list):
                             results_list = analysis_response
                         elif isinstance(analysis_response, dict) and 'items' in analysis_response:
                             results_list = analysis_response['items']
                             # TODO: Add pagination handling if API supports it and many results are expected
                         elif analysis_response is not None:
                              st.warning("Could not load analysis results: Unexpected format received from API.")
                         st.session_state.selected_meeting_analyses = results_list

                 analyses = st.session_state.selected_meeting_analyses

                 if isinstance(analyses, list):
                     if analyses:
                         participants = None
                         try:
                             if isinstance(st.session_state.history_meetings_list, list):
                                 meeting_info = next((m for m in st.session_state.history_meetings_list if m.get('id') == current_selected_meeting_id_hist), None)
                                 if meeting_info:
                                     participants = meeting_info.get('participants')
                         except Exception: pass

                         st.markdown(f"**Found {len(analyses)} analysis result(s):**")
                         sorted_analyses = sorted(analyses, key=lambda x: x.get('created_at', '1970-01-01'), reverse=True)

                         for idx, analysis_result in enumerate(sorted_analyses):
                             transcript_id_hist = analysis_result.get('transcript_id')
                             if not transcript_id_hist: continue
                             analysis_title = analysis_result.get('transcript_title', f"Transcript ID: {transcript_id_hist}")
                             created_at_str = ""
                             try:
                                 created_at = analysis_result.get('created_at')
                                 if created_at: created_at_str = f" (Analyzed: {datetime.fromisoformat(str(created_at).replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M')})"
                             except: pass

                             expander_label = f"{analysis_title}{created_at_str}"
                             with st.expander(expander_label, expanded=idx == 0):
                                 display_analysis_results(analysis_result, participants=participants, include_json_expander=False)
                                 st.info("To ask questions about this transcript, please use the 'Q&A' tab.")
                     else:
                         st.info("No analysis results found for this meeting.")

    with tab_qanda:
        st.header("Ask Questions (Q&A)")
        st.subheader("Step 1: Select Meeting for Q&A")
        if st.session_state.qanda_meetings_list is None:
            with st.spinner("Loading meetings..."):
                meetings = make_request("GET","/meetings/", params={"limit": 500, "ordering": "-meeting_date"})
                if isinstance(meetings, list):
                    st.session_state.qanda_meetings_list = meetings
                else:
                    st.session_state.qanda_meetings_list = []

        selected_meeting_id_qanda = None
        meetings_list_qanda = st.session_state.qanda_meetings_list

        if isinstance(meetings_list_qanda, list) and meetings_list_qanda:
            meeting_options_qanda = {"-- Select --": None}
            for m in meetings_list_qanda:
                m_id, m_title, m_date_str = m.get('id'), m.get('title', 'Untitled'), m.get('meeting_date', '')
                try: m_date_formatted = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                except: m_date_formatted = m_date_str if m_date_str else "Invalid Date"
                label = f"{m_title} ({m_date_formatted}) - ID:{m_id}"
                meeting_options_qanda[label] = m_id

            selected_label_qanda = st.selectbox("Select Meeting:", options=list(meeting_options_qanda.keys()), key="qanda_meeting_select")
            selected_meeting_id_qanda = meeting_options_qanda.get(selected_label_qanda)
            if st.session_state.qanda_selected_meeting_id != selected_meeting_id_qanda:
                st.session_state.qanda_selected_meeting_id = selected_meeting_id_qanda
                st.session_state.qanda_available_transcripts = None
                st.session_state.qanda_transcript_select = "-- Select --"
                st.session_state.qanda_selected_transcript_id = None
                st.session_state.qanda_selected_transcript_status = None

        elif isinstance(meetings_list_qanda, list) and not meetings_list_qanda:
             st.info("No meetings available to select for Q&A.")

        st.divider()
        if selected_meeting_id_qanda:
            st.subheader("Step 2: Select Transcript")
            if st.session_state.qanda_available_transcripts is None:
                 with st.spinner(f"Loading analyzed transcripts for Meeting ID {selected_meeting_id_qanda}..."):
                    analysis_endpoint = f"/analysis/meeting/{selected_meeting_id_qanda}/"
                    analysis_response = make_request("GET", analysis_endpoint, params={"limit": 100})

                    transcripts_list = []
                    if isinstance(analysis_response, list):
                        transcripts_list = analysis_response
                    elif isinstance(analysis_response, dict) and 'items' in analysis_response:
                        transcripts_list = analysis_response['items']
                    elif analysis_response is not None:
                        st.warning("Could not load transcripts/analyses: Unexpected format.")
                    valid_analyses = [a for a in transcripts_list if a.get('transcript_id')]
                    st.session_state.qanda_available_transcripts = sorted(valid_analyses, key=lambda x: x.get('created_at', '1970-01-01'), reverse=True)
            available_analyses_qanda = st.session_state.qanda_available_transcripts
            selected_transcript_id_qanda = None

            if isinstance(available_analyses_qanda, list) and available_analyses_qanda:
                transcript_options_qanda = {"-- Select --": None}
                for a in available_analyses_qanda:
                    t_id = a['transcript_id']
                    t_title = a.get('transcript_title', f"Transcript ID: {t_id}")
                    created_at_str = ""
                    try:
                         created_at = a.get('created_at')
                         if created_at: created_at_str = f" (Analyzed: {datetime.fromisoformat(str(created_at).replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M')})"
                    except: pass
                    label = f"{t_title}{created_at_str}"
                    transcript_options_qanda[label] = t_id

                selected_label_transcript_qanda = st.selectbox("Select Transcript:",
                                                               options=list(transcript_options_qanda.keys()), key="qanda_transcript_select" )
                selected_transcript_id_qanda = transcript_options_qanda.get(selected_label_transcript_qanda)
                if st.session_state.qanda_selected_transcript_id != selected_transcript_id_qanda:
                    st.session_state.qanda_selected_transcript_id = selected_transcript_id_qanda
                    st.session_state.qanda_selected_transcript_status = None
                    st.rerun()

            elif isinstance(available_analyses_qanda, list) and not available_analyses_qanda:
                 st.info("No analyzed transcripts found for this meeting.")
            if selected_transcript_id_qanda:
                st.subheader("Step 3: Check Status & Ask Questions")
                force_check = st.button("🔄 Refresh Q&A Status", key=f"qanda_refresh_{selected_transcript_id_qanda}")
                if st.session_state.qanda_selected_transcript_status is None or force_check:
                    with st.spinner(f"Checking Q&A status for Transcript `{selected_transcript_id_qanda}`..."):
                        embed_stat_resp_qanda = make_request("GET", f"/chatbot/status/{selected_transcript_id_qanda}/", suppress_errors=True)
                        status_val = "CHECK_FAILED"
                        if isinstance(embed_stat_resp_qanda, dict):
                             status_val = embed_stat_resp_qanda.get('embedding_status', 'Unknown')
                        st.session_state.qanda_selected_transcript_status = {"status": status_val, "checked_at": datetime.now()}
                        if force_check:
                            st.rerun()
                current_status_info = st.session_state.qanda_selected_transcript_status
                if current_status_info:
                    status = current_status_info["status"]
                    checked_time_str = current_status_info["checked_at"].strftime('%Y-%m-%d %H:%M:%S')

                    if status == "COMPLETED":
                        st.success(f"✅ Q&A Ready (Status checked: {checked_time_str})")
                        display_chatbot_interface(selected_transcript_id_qanda)
                    elif status in ["PENDING", "PROCESSING", "NONE"]:
                        st.info(f"⏳ Q&A Preparation Status: **{status}**. Please wait or refresh status. (Checked: {checked_time_str})")
                    elif status == "FAILED":
                        st.error(f"❌ Q&A Preparation Failed. Cannot ask questions. (Checked: {checked_time_str})")
                    elif status == "CHECK_FAILED":
                        st.error(f"⚠️ Could not check Q&A status. Please try refreshing. (Last attempt: {checked_time_str})")
                    else:
                        st.warning(f"❓ Unknown Q&A Status: **{status}**. Cannot ask questions. (Checked: {checked_time_str})")
                else:
                     if selected_transcript_id_qanda:
                         st.spinner("Checking Q&A status...")

elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar to access the application.")
