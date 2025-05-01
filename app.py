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
        st.warning("No refresh token available. Please log in again.")
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
            refreshed = refresh_token()
            if refreshed:
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

        if response.status_code == 204: return True
        elif response.status_code in [200, 201, 202]:
            if response.text:
                try: return response.json()
                except json.JSONDecodeError:
                    if not suppress_errors: st.warning(f"API returned non-JSON response (Status: {response.status_code}).")
                    return response.text
            else:
                return True
        else:
            if not suppress_errors: st.warning(f"Unexpected success status code: {response.status_code}")
            return response.text if response.text else True

    except requests.exceptions.HTTPError as e:
        if not suppress_errors:
            st.error(f"HTTP Error: {e}" + (f" (Status: {e.response.status_code})" if e.response else ""))
            if e.response:
                try:
                    err_data = e.response.json()
                    detail = err_data.get('detail', json.dumps(err_data))
                    if isinstance(detail, list): detail = "; ".join(map(str, detail))
                    elif not isinstance(detail, str): detail = json.dumps(detail)
                    st.error(f"Detail: {detail}")
                except json.JSONDecodeError:
                    st.error(f"Raw Error: {e.response.text[:500]}...")
        return None
    except requests.exceptions.ConnectionError as e:
        if not suppress_errors: st.error(f"Connection Error: Could not connect to API at {api_base}. Details: {e}")
        return None
    except requests.exceptions.Timeout as e:
        if not suppress_errors: st.error(f"Request Timeout: The API did not respond within {timeout} seconds. Details: {e}")
        return None
    except requests.exceptions.RequestException as e:
        if not suppress_errors: st.error(f"Request Failed: An ambiguous request error occurred. Details: {e}")
        return None
    except Exception as e:
        if not suppress_errors: st.error(f"An unexpected error occurred in make_request: {e}")
        st.error(traceback.format_exc())
        return None

def display_analysis_results(result, participants: Optional[List[Any]] = None, include_json_expander=True):
    if not isinstance(result, dict):
        st.warning("Invalid analysis result format received.")
        st.json(result)
        return

    tx_id = result.get('transcript_id', 'N/A')
    tx_title = result.get('transcript_title')

    st.markdown(f"**Transcript ID:** `{tx_id}`" + (f" | **Title:** *{tx_title}*" if tx_title else ""))

    col1, col2 = st.columns([2, 1])

    with col1:
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
                     deadline_dt = datetime.strptime(str(deadline), "%Y-%m-%d").date()
                     deadline_str = deadline_dt.strftime("%B %d, %Y")
                 except (ValueError, TypeError):
                     st.warning(f"Could not parse deadline format: {deadline}")
                     deadline_str = str(deadline)
             st.markdown(f"**Deadline:** {deadline_str or '_N/A_'}")
        else:
            st.info("No action items identified.")

        st.subheader("👥 Participants")
        st.markdown(f"{', '.join(map(str, participants))}" if participants else "_N/A_")

        st.caption("---")
        ts_created = result.get('created_at')
        ts_updated = result.get('updated_at')
        dt_created = None
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
    st.subheader(f"💬 Ask a Question about Transcript {transcript_id}")
    qa_form_key = f"qa_form_{transcript_id}"
    qa_input_key = f"qa_input_{transcript_id}"
    last_q_key = f'last_question_{transcript_id}'
    last_a_key = f'last_answer_{transcript_id}'
    last_e_key = f'last_error_{transcript_id}'

    with st.form(qa_form_key, clear_on_submit=False):
        user_question = st.text_input("Your Question:", key=qa_input_key, value=st.session_state.get(last_q_key, ""))
        submit_qa = st.form_submit_button("Ask")

        if submit_qa and user_question:
            st.session_state[last_q_key] = user_question
            with st.spinner("Thinking..."):
                qa_payload = {"question": user_question}
                answer_resp = make_request("POST", f"/chatbot/ask/{transcript_id}/", json_data=qa_payload, timeout=90)

                if isinstance(answer_resp, dict) and 'answer' in answer_resp:
                    st.session_state[last_a_key] = answer_resp['answer']
                    st.session_state[last_e_key] = None
                else:
                     st.session_state[last_a_key] = None
                     st.session_state[last_e_key] = "Failed to get an answer from the API."
            st.rerun()

    last_q = st.session_state.get(last_q_key)
    last_a = st.session_state.get(last_a_key)
    last_e = st.session_state.get(last_e_key)

    if last_q:
        st.markdown(f"**Your Question:** {last_q}")
        if last_a:
            st.markdown("**Answer:**")
            st.info(last_a)
        elif last_e:
            st.error(last_e)

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
                    st.caption(f"Session valid for approx. {mins} min")
            except: pass
        if st.button("Logout", key="logout_button"):
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
        'meeting_action': "Select Existing Meeting",
        'select_meeting_dropdown': "-- Select --",
        'history_filter_title': "",
        'history_filter_date_from': None,
        'history_filter_date_to': None,
        'history_meeting_select': "-- Select --",
        'selected_meeting_id_history': None,
        'analysis_tab_meetings_list': None,
        'history_meetings_list': None,
        'selected_meeting_analyses': None,
        'chatbot_statuses': {},
    }
    for key, default in default_session_keys.items():
        if key not in st.session_state:
            st.session_state[key] = default
    just_created_meeting_id = st.session_state.pop('just_created_meeting_id', None)
    if just_created_meeting_id:
        st.session_state.meeting_action = "Select Existing Meeting"
        st.session_state.analysis_tab_meetings_list = None
        st.success(f"Meeting ID {just_created_meeting_id} created. Select it below.")
    tab_analysis, tab_history = st.tabs(["✨ New Analysis", "📂 History / Q&A"])
    with tab_analysis:
        st.header("Submit New Transcript for Analysis")
        st.subheader("Step 1: Select or Create Meeting")
        meeting_action = st.radio(
            "Choose Action:",
            ["Select Existing Meeting", "Create New Meeting"],
            key="meeting_action",
            horizontal=True
        )
        selected_meeting_id = None
        selected_meeting_title = None
        if st.session_state.meeting_action == "Select Existing Meeting":
            if st.session_state.analysis_tab_meetings_list is None:
                with st.spinner("Loading meetings..."):
                    meetings = make_request("GET","/meetings/", params={"limit": 500})
                    if isinstance(meetings, list):
                        st.session_state.analysis_tab_meetings_list = meetings
                    else:
                        st.session_state.analysis_tab_meetings_list = []
                        st.warning("Could not load meetings.")

            meetings_list = st.session_state.analysis_tab_meetings_list
            if meetings_list:
                try: sorted_meetings = sorted(meetings_list, key=lambda m: m.get('meeting_date', ''), reverse=True)
                except: sorted_meetings = meetings_list

                meeting_options = {"-- Select --": None}
                for m in sorted_meetings:
                    m_id, m_title, m_date_str = m.get('id'), m.get('title', 'Untitled'), m.get('meeting_date', '')
                    try: m_date_formatted = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                    except: m_date_formatted = m_date_str
                    label = f"{m_title} ({m_date_formatted}) - ID:{m_id}"
                    meeting_options[label] = m_id

                options_list = list(meeting_options.keys())
                current_selection_label = st.session_state.select_meeting_dropdown
                selected_index = 0
                if current_selection_label in options_list:
                     try: selected_index = options_list.index(current_selection_label)
                     except ValueError: st.session_state.select_meeting_dropdown = "-- Select --"

                selected_label = st.selectbox("Select Meeting:", options=options_list, index=selected_index, key="select_meeting_dropdown")
                selected_meeting_id = meeting_options.get(selected_label)
                if selected_meeting_id: selected_meeting_title = selected_label.split(" (")[0]
            else:
                st.info("No meetings found. You can create a new one.")
        elif st.session_state.meeting_action == "Create New Meeting":
             with st.form("create_meeting_form"):
                new_title = st.text_input("New Meeting Title*", key="new_meeting_title_input")
                submitted_create = st.form_submit_button("Create Meeting")
                if submitted_create:
                    if new_title.strip():
                        with st.spinner("Creating meeting..."):
                            create_payload = {"title": new_title.strip()}
                            response = make_request("POST", "/meetings/", json_data=create_payload)
                        if isinstance(response, dict) and 'id' in response:
                            st.success(f"Meeting '{response.get('title')}' created (ID: {response['id']}).")
                            if st.session_state.analysis_tab_meetings_list is None: st.session_state.analysis_tab_meetings_list = []
                            st.session_state.analysis_tab_meetings_list.append(response)
                            st.session_state.just_created_meeting_id = response['id']
                            st.rerun()
                        else: st.error("Failed to create meeting.")
                    else: st.warning("Meeting title cannot be empty.")
        if selected_meeting_id:
            st.divider()
            st.subheader(f"Step 2: Add Transcript to '{selected_meeting_title or f'Meeting ID:{selected_meeting_id}'}'")

            with st.form("transcript_submit_form", clear_on_submit=True):
                input_method = st.radio("Input Method:", ["Paste Text", "Upload File"], key="transcript_input_method", horizontal=True)
                transcript_text_input = None
                uploaded_file_input = None

                if input_method == "Paste Text":
                    transcript_text_input = st.text_area("Paste Transcript Text Here:", height=200, key="transcript_raw_text_input")
                else:
                    uploaded_file_input = st.file_uploader("Upload Transcript File:", type=['txt', 'pdf', 'md', 'docx'], key="transcript_file_uploader")

                submit_transcript = st.form_submit_button("🚀 Submit for Analysis")

                if submit_transcript:
                    api_endpoint, request_payload, request_files = None, None, None
                    if input_method == "Paste Text":
                        if transcript_text_input and transcript_text_input.strip():
                            api_endpoint, request_payload = f"/transcripts/{selected_meeting_id}/", {'raw_text': transcript_text_input}
                        else: st.warning("Pasted text cannot be empty.")
                    elif input_method == "Upload File":
                        if uploaded_file_input:
                            api_endpoint, request_files = f"/transcripts/{selected_meeting_id}/upload/", {'file': (uploaded_file_input.name, uploaded_file_input.getvalue(), uploaded_file_input.type)}
                        else: st.warning("Please upload a file.")

                    if api_endpoint and (request_payload or request_files):
                        with st.spinner("Submitting transcript..."):
                            submission_response = make_request("POST", api_endpoint, json_data=request_payload, files=request_files)

                        if isinstance(submission_response, dict) and 'id' in submission_response:
                            transcript_id = submission_response['id']
                            initial_analysis_status = submission_response['processing_status']
                            meeting_id_from_resp = submission_response.get('meeting_id')
                            st.success(f"✅ Transcript submitted successfully (ID: {transcript_id}). Analysis queued.")
                            st.info(f"Initial Analysis Status: {initial_analysis_status}")
                            analysis_status_placeholder = st.status(f"Processing Analysis for Transcript {transcript_id}...", expanded=True)
                            max_analysis_attempts, polling_interval = 60, 5
                            analysis_attempt = 0
                            analysis_completed = False
                            final_analysis_result, final_meeting_participants = None, None
                            current_analysis_status = initial_analysis_status
                            while analysis_attempt < max_analysis_attempts and not analysis_completed:
                                analysis_attempt += 1; time.sleep(polling_interval)
                                analysis_status_placeholder.write(f"Checking analysis status (Attempt {analysis_attempt}/{max_analysis_attempts})...")
                                status_response = make_request("GET", f"/transcripts/status/{transcript_id}/", suppress_errors=True)
                                if isinstance(status_response, dict) and 'processing_status' in status_response:
                                    current_analysis_status = status_response['processing_status']
                                    if not meeting_id_from_resp: meeting_id_from_resp = status_response.get('meeting_id')
                                    analysis_status_placeholder.update(label=f"Tx {transcript_id}: Analysis Status - {current_analysis_status}")
                                    if current_analysis_status == "COMPLETED":
                                        analysis_completed = True
                                        analysis_status_placeholder.write("Analysis complete! Fetching results...")
                                        analysis_result_response = make_request("GET", f"/analysis/transcript/{transcript_id}/")
                                        if isinstance(analysis_result_response, dict):
                                            final_analysis_result = analysis_result_response
                                            analysis_status_placeholder.write("Analysis results received.")
                                            if meeting_id_from_resp:
                                                 meeting_details = make_request("GET", f"/meetings/{meeting_id_from_resp}/")
                                                 final_meeting_participants = meeting_details.get('participants') if isinstance(meeting_details, dict) else None
                                            analysis_status_placeholder.update(label="Analysis Complete!", state="complete", expanded=False)
                                            st.success("📊 Analysis processing finished.")
                                        else:
                                            st.error("Failed to fetch completed analysis results.")
                                            analysis_status_placeholder.error("Failed to fetch analysis results.")
                                            analysis_status_placeholder.update(label="Error Fetching Results", state="error")
                                    elif current_analysis_status == "FAILED":
                                        error_msg = status_response.get('processing_error', 'Unknown error')
                                        st.error(f"Analysis process failed for Transcript {transcript_id}.")
                                        analysis_status_placeholder.error(f"Analysis Failed: {error_msg}")
                                        analysis_status_placeholder.update(label="Analysis Failed", state="error")
                                        analysis_completed = True
                                    elif current_analysis_status not in ["PENDING", "PROCESSING"]:
                                        st.warning(f"Unknown analysis status: {current_analysis_status}")
                                        analysis_status_placeholder.update(label=f"Unknown Status: {current_analysis_status}", state="error")
                                        analysis_completed = True
                                else:
                                    analysis_status_placeholder.warning(f"Analysis status check failed (Attempt {analysis_attempt}). Retrying...")
                                    if analysis_attempt > 5 and status_response is None:
                                         analysis_status_placeholder.error("Analysis status check failed repeatedly.")
                                         analysis_status_placeholder.update(label="Error Checking Status", state="error")
                                         analysis_completed = True

                            if analysis_attempt >= max_analysis_attempts and not analysis_completed:
                                st.warning(f"Analysis polling timed out.")
                                analysis_status_placeholder.warning(f"Polling Timeout. Status: {current_analysis_status}")
                                analysis_status_placeholder.update(label="Analysis Polling Timeout", state="warning")

                            if final_analysis_result:
                                display_analysis_results(final_analysis_result, participants=final_meeting_participants)
                                st.divider(); st.subheader("Q&A Status")
                                embedding_status_placeholder = st.empty()
                                embedding_status_placeholder.info("Checking Q&A availability...")
                                embed_stat_resp = make_request("GET", f"/chatbot/status/{transcript_id}/", suppress_errors=True)
                                if isinstance(embed_stat_resp, dict) and 'embedding_status' in embed_stat_resp:
                                    embedding_status = embed_stat_resp['embedding_status']
                                    if embedding_status == "COMPLETED":
                                        embedding_status_placeholder.success("✅ Q&A is ready!")
                                        display_chatbot_interface(transcript_id)
                                    elif embedding_status in ["PENDING", "PROCESSING", "NONE"]:
                                         embedding_status_placeholder.info(f"⏳ Q&A preparing... (Status: {embedding_status})")
                                    elif embedding_status == "FAILED":
                                         embedding_status_placeholder.error("❌ Q&A preparation failed.")
                                    else: embedding_status_placeholder.warning(f"❓ Unknown Q&A status: {embedding_status}")
                                else: embedding_status_placeholder.warning("⚠️ Could not check Q&A status.")

                            elif not analysis_completed and current_analysis_status != "FAILED":
                                 st.error("Analysis did not complete. Cannot display results or Q&A.")

                            if 'history_meetings_list' in st.session_state: del st.session_state.history_meetings_list
                            if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
                            if 'chatbot_statuses' in st.session_state: st.session_state.chatbot_statuses = {}


                        elif submission_response is None: st.error("❌ Transcript submission failed (Connection/Auth Error).")
                        else: st.error("❌ Transcript submission failed (API Error).")

        else:
            st.info("Select or create a meeting above to submit a transcript.")
    with tab_history:
        st.header("View History & Ask Questions")
        st.subheader("Filter Meetings")
        filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
        with filter_col1: st.text_input("Filter by Title:", key="history_filter_title")
        with filter_col2: st.date_input("Filter From Date:", key="history_filter_date_from")
        with filter_col3: st.date_input("Filter To Date:", key="history_filter_date_to")
        if st.button("🔄 Load / Filter Meetings", key="load_history_button", use_container_width=True):
            st.session_state.selected_meeting_id_history = None
            st.session_state.history_meeting_select = "-- Select --"
            if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
            if 'chatbot_statuses' in st.session_state: st.session_state.chatbot_statuses = {}
            with st.spinner("Loading meetings..."):
                filter_params = {'limit': 500}
                if st.session_state.history_filter_title: filter_params['title'] = st.session_state.history_filter_title
                if st.session_state.history_filter_date_from: filter_params['date_from'] = st.session_state.history_filter_date_from.isoformat()
                if st.session_state.history_filter_date_to:
                    filter_params['date_to'] = (st.session_state.history_filter_date_to + timedelta(days=1)).isoformat()

                meetings_data = make_request("GET", "/meetings/", params=filter_params)
                if isinstance(meetings_data, list):
                    st.session_state.history_meetings_list = meetings_data
                    st.success(f"Loaded {len(meetings_data)} meetings.")
                else:
                    st.session_state.history_meetings_list = []
                    st.warning("Failed to load meetings or none found.")

        current_selected_meeting_id_hist = None
        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list is not None:
            meetings_list_hist = st.session_state.history_meetings_list
            if meetings_list_hist:
                try: sorted_meetings_hist = sorted(meetings_list_hist, key=lambda m: m.get('meeting_date', ''), reverse=True)
                except: sorted_meetings_hist = meetings_list_hist

                meeting_options_hist = {"-- Select --": None}
                for m in sorted_meetings_hist:
                    m_id, m_title, m_date_str = m.get('id'), m.get('title', 'Untitled'), m.get('meeting_date', '')
                    try: m_date_formatted = datetime.fromisoformat(m_date_str.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M') if m_date_str else 'No Date'
                    except: m_date_formatted = m_date_str
                    label = f"{m_title} ({m_date_formatted}) - ID:{m_id}"
                    meeting_options_hist[label] = m_id

                options_list_hist = list(meeting_options_hist.keys())
                current_selection_label_hist = st.session_state.history_meeting_select
                selected_index_hist = 0
                if current_selection_label_hist in options_list_hist:
                     try: selected_index_hist = options_list_hist.index(current_selection_label_hist)
                     except ValueError: st.session_state.history_meeting_select = "-- Select --"

                selected_label_hist = st.selectbox("Select Meeting to View:", options=options_list_hist, index=selected_index_hist, key="history_meeting_select")
                current_selected_meeting_id_hist = meeting_options_hist.get(selected_label_hist)

                previous_selected_id_hist = st.session_state.get('selected_meeting_id_history')
                if previous_selected_id_hist != current_selected_meeting_id_hist:
                     if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
                     if 'chatbot_statuses' in st.session_state: st.session_state.chatbot_statuses = {}
                     st.session_state.selected_meeting_id_history = current_selected_meeting_id_hist
                     st.rerun()

            elif meetings_list_hist == []: st.info("No meetings match the current filters.")

        if current_selected_meeting_id_hist:
            st.divider()
            action_col1, action_col2, action_col3 = st.columns([1, 2, 4])

            with action_col3: st.subheader(f"Details for: {st.session_state.history_meeting_select}")
            with action_col1:
                 delete_button_key, confirm_key = f"delete_meeting_{current_selected_meeting_id_hist}", f"confirm_delete_{current_selected_meeting_id_hist}"
                 if st.button("🗑️", key=delete_button_key, help="Delete this meeting"): st.session_state[confirm_key] = True; st.rerun()
                 if st.session_state.get(confirm_key):
                     st.warning(f"**Confirm Deletion?** Meeting ID {current_selected_meeting_id_hist} and all related data will be lost.")
                     confirm_col1, confirm_col2 = st.columns(2)
                     with confirm_col1:
                         if st.button("✅ Yes, Delete", key=f"confirm_yes_{current_selected_meeting_id_hist}"):
                             with st.spinner("Deleting meeting..."): delete_resp = make_request("DELETE", f"/meetings/{current_selected_meeting_id_hist}/")
                             if confirm_key in st.session_state: del st.session_state[confirm_key]
                             if delete_resp is True:
                                 st.success("Meeting deleted."); st.session_state.history_meetings_list = None; st.session_state.selected_meeting_id_history = None; st.session_state.history_meeting_select = "-- Select --"; st.rerun()
                             else: st.error("Failed to delete meeting."); st.rerun()
                     with confirm_col2:
                         if st.button("❌ No, Cancel", key=f"confirm_no_{current_selected_meeting_id_hist}"):
                             if confirm_key in st.session_state: del st.session_state[confirm_key]; st.rerun()

            with action_col2:
                if not st.session_state.get(confirm_key):
                    if st.button(f"📊 Show/Refresh Analyses", key=f"show_analyses_{current_selected_meeting_id_hist}"):
                        analysis_endpoint = f"/analysis/meeting/{current_selected_meeting_id_hist}/"
                        with st.spinner("Fetching analysis results..."):
                            analysis_response = make_request("GET", analysis_endpoint, params={"limit": 100})

                        results_list = []
                        if isinstance(analysis_response, dict) and 'items' in analysis_response:
                            results_list = analysis_response['items']; total_count = analysis_response.get('count', len(results_list))
                            st.info(f"Showing {len(results_list)} of {total_count} results.")
                        elif isinstance(analysis_response, list): results_list = analysis_response
                        elif analysis_response is not None: st.warning("Could not load analysis results.")

                        st.session_state.selected_meeting_analyses = results_list
                        st.session_state.chatbot_statuses = {}
                        if not results_list and analysis_response is not None: st.info("No analysis results found.")
                        st.rerun()

            if not st.session_state.get(confirm_key) and 'selected_meeting_analyses' in st.session_state:
                analyses = st.session_state.selected_meeting_analyses
                if analyses:
                    participants = None
                    try: meeting_info = next(m for m in st.session_state.history_meetings_list if m.get('id') == current_selected_meeting_id_hist); participants = meeting_info.get('participants')
                    except: pass

                    st.write(f"Displaying {len(analyses)} analysis result(s):")
                    sorted_analyses = sorted(analyses, key=lambda x: x.get('created_at', ''), reverse=True)

                    for idx, analysis_result in enumerate(sorted_analyses):
                        transcript_id_hist = analysis_result.get('transcript_id')
                        if not transcript_id_hist: continue
                        transcript_title_hist = analysis_result.get('transcript_title')
                        expander_label = f"Analysis for Tx ID: {transcript_id_hist}" + (f' - "{transcript_title_hist}"' if transcript_title_hist else "")

                        with st.expander(expander_label, expanded=idx == 0):
                            display_analysis_results(analysis_result, participants=participants, include_json_expander=False)
                            embedding_status_hist = st.session_state.chatbot_statuses.get(transcript_id_hist)
                            qa_check_key = f"check_qa_{transcript_id_hist}"
                            qa_status_col, qa_button_col = st.columns([3,1])

                            with qa_status_col:
                                status_text = "Q&A Status: "
                                if embedding_status_hist is None: status_text += "Not checked yet."
                                elif embedding_status_hist == "COMPLETED": status_text += "✅ Ready"
                                elif embedding_status_hist == "FAILED": status_text += "❌ Failed"
                                elif embedding_status_hist == "Unknown": status_text += "⚠️ Unknown (Check Failed)"
                                else: status_text += f"⏳ Preparing ({embedding_status_hist})"
                                st.caption(status_text)

                            with qa_button_col:
                                if st.button("🔄 Check", key=qa_check_key, help="Refresh Q&A status"):
                                     with st.spinner("Checking Q&A status..."):
                                         embed_stat_resp_hist = make_request("GET", f"/chatbot/status/{transcript_id_hist}/", suppress_errors=True)
                                     if isinstance(embed_stat_resp_hist, dict): embedding_status_hist = embed_stat_resp_hist.get('embedding_status', 'Unknown')
                                     else: embedding_status_hist = "Unknown"
                                     st.session_state.chatbot_statuses[transcript_id_hist] = embedding_status_hist
                                     st.rerun()
                            if embedding_status_hist == "COMPLETED":
                                display_chatbot_interface(transcript_id_hist)
                        st.markdown("---")
                elif analyses == []: st.info("No analysis results loaded or found.")

elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar to access the application.")