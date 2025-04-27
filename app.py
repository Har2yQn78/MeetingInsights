import streamlit as st
import requests
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Any
import io

st.set_page_config(layout="wide", page_title="Meeting Analysis")

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
        st.session_state.token_expiry = datetime.now() + timedelta(hours=6)
        st.session_state.logged_in = True
        st.session_state.username = username
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json().get("detail", "Unknown error")
                st.error(f"API Error: {error_detail}")
            except json.JSONDecodeError:
                 st.error(f"API Error: Status {e.response.status_code} - {e.response.text}")
        st.session_state.logged_in = False
        if 'access_token' in st.session_state: del st.session_state.access_token
        if 'refresh_token' in st.session_state: del st.session_state.refresh_token
        if 'token_expiry' in st.session_state: del st.session_state.token_expiry
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
        st.session_state.token_expiry = datetime.now() + timedelta(hours=6)
        st.session_state.logged_in = True
        st.info("Token refreshed successfully.")
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Session expired or token invalid. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None and e.response.status_code in [401, 400]:
             st.error("Reason: Refresh token is invalid or has expired.")
        logout()
        return False

def logout():
    keys_to_remove = list(st.session_state.keys())
    st.info("Logging out...")
    for key in keys_to_remove:
        if key in ['access_token', 'refresh_token', 'token_expiry', 'logged_in', 'username',
                   'history_meetings_list', 'selected_meeting_analyses', '_cached_analysis_meeting_id',
                   'selected_meeting_id_history', 'history_meeting_select']:
            try:
                del st.session_state[key]
            except KeyError:
                pass
    st.success("Logged out successfully.")


def ensure_authenticated():
    if not st.session_state.get('logged_in', False) or 'access_token' not in st.session_state:
        return False

    buffer_seconds = 30
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=buffer_seconds)):
        st.info("Access token nearing expiry or expired, attempting refresh...")
        if not refresh_token():
            st.warning("Session expired. Please log in again.")
            st.rerun()
            return False
        else:
             pass
    return True

def get_headers(include_content_type=True):
    if 'access_token' not in st.session_state:
         st.error("Authentication token missing unexpectedly. Please log in.")
         logout()
         st.rerun()
         return None
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers

def make_request(method, endpoint, json_data=None, data=None, files=None, timeout=30, **kwargs):
    if not ensure_authenticated():
        st.warning("Authentication required. Please log in.")
        return None

    include_content_type = json_data is not None and not files and not data
    headers = get_headers(include_content_type=include_content_type)
    if headers is None:
        st.error("Failed to prepare authorization headers.")
        return None

    url = f"{API_BASE_URL}{endpoint}"

    try:
        response = requests.request(
            method, url, headers=headers, json=json_data, data=data, files=files, timeout=timeout, **kwargs
        )

        if response.status_code == 401:
            st.warning("Received 401 Unauthorized. Attempting token refresh...")
            if refresh_token():
                headers = get_headers(include_content_type=include_content_type)
                if headers is None: return None
                st.info("Retrying request with refreshed token...")
                response = requests.request(method, url, headers=headers, json=json_data, data=data, files=files, timeout=timeout, **kwargs)
                if response.status_code == 401:
                    st.error("Authentication still failed after token refresh. Check permissions or log in again.")
                    logout()
                    st.rerun()
                    return None
            else:
                st.error("Token refresh failed during retry. Please log in again.")
                st.rerun()
                return None

        response.raise_for_status()

        if response.status_code == 204:
            return True
        elif response.status_code == 202:
            st.info(f"Request accepted by API (Status {response.status_code}). Background processing likely started.")
            try:
                return response.json()
            except json.JSONDecodeError:
                return True
        elif response.text:
            try:
                return response.json()
            except json.JSONDecodeError:
                st.warning(f"API returned status {response.status_code} but response is not valid JSON.")
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
                st.error("Raw Error Response:")
                st.text(http_err.response.text)
        return None
    except requests.exceptions.ConnectionError as conn_err:
        st.error(f"Connection Error: Failed to connect to API at {API_BASE_URL}. Is the server running?")
        st.error(f"Details: {conn_err}")
        return None
    except requests.exceptions.Timeout as timeout_err:
        st.error(f"Request Timed Out: The API server did not respond in {timeout} seconds.")
        st.error(f"Details: {timeout_err}")
        return None
    except requests.exceptions.RequestException as req_err:
        st.error(f"Request Failed: An unexpected error occurred during the request.")
        st.error(f"Details: {req_err}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred in make_request function: {e}")
        import traceback
        st.error(traceback.format_exc())
        return None

def extract_text_from_pdf(file_content: bytes) -> str:
    try:
        import fitz
        with fitz.open(stream=file_content, filetype="pdf") as doc:
            text = ""
            for page in doc:
                text += page.get_text()
        if not text.strip():
             st.warning("Extracted PDF text appears empty.")
        return text
    except ImportError:
        st.error("PyMuPDF library not found. Cannot extract text from PDF.")
        st.error("Please install it: pip install pymupdf")
        raise ValueError("PDF processing library missing.")
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        raise ValueError(f"Could not process PDF file: {e}")

def extract_text_from_txt(file_content: bytes) -> str:
    try:
        return file_content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            st.warning("Could not decode file as UTF-8, trying Latin-1.")
            return file_content.decode('latin-1')
        except Exception as e:
            st.error(f"Error decoding text file even with Latin-1 fallback: {e}")
            raise ValueError("Could not decode text file. Ensure it's UTF-8 or Latin-1 encoded.")
    except Exception as e:
        st.error(f"Error reading text file content: {e}")
        raise ValueError(f"Could not read text file: {e}")


def extract_text_from_uploaded_file(uploaded_file) -> Optional[str]:
    if uploaded_file is None:
        return None

    file_content = uploaded_file.getvalue()
    file_type = uploaded_file.type
    file_name = uploaded_file.name

    st.write(f"Attempting to extract text from '{file_name}' (Type: {file_type})...")

    try:
        if file_type == "application/pdf":
            return extract_text_from_pdf(file_content)
        elif file_type == "text/plain":
            return extract_text_from_txt(file_content)
        else:
            st.warning(f"Unsupported file type: {file_type}. Trying to read as plain text...")
            return extract_text_from_txt(file_content)
    except ValueError as e:
        st.error(f"Failed to extract text from {file_name}: {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during text extraction for {file_name}: {e}")
        return None

def display_analysis_results(result, participants: Optional[List[Any]] = None, include_json_expander=True):
    if not isinstance(result, dict):
        st.warning("Invalid analysis result format received.")
        st.json(result)
        return

    st.markdown(f"**Transcript ID:** `{result.get('transcript_id', 'N/A')}`")

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
        deadline = result.get('deadline')
        if task or responsible or deadline:
             st.markdown(f"**Task:** {task if task else '_Not specified_'}")
             st.markdown(f"**Responsible:** {responsible if responsible else '_Not specified_'}")
             deadline_str = deadline
             if deadline:
                 try:
                    deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
                    deadline_str = deadline_dt.strftime("%B %d, %Y")
                 except (ValueError, TypeError):
                     deadline_str = deadline
             st.markdown(f"**Deadline:** {deadline_str if deadline_str else '_Not specified_'}")
        else:
             st.info("No specific action item extracted.")

        st.subheader("👥 Participants")
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
            st.markdown("_Participants data not available._")

        st.caption("---")
        created_at_str = result.get('created_at')
        updated_at_str = result.get('updated_at')
        created_dt = None
        try:
            if created_at_str:
                created_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                st.caption(f"Analyzed: {created_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            if updated_at_str:
                updated_dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                if created_dt is None or abs((updated_dt - created_dt).total_seconds()) > 5:
                     st.caption(f"Updated: {updated_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except (ValueError, TypeError) as parse_err:
             st.warning(f"Could not parse timestamp: {parse_err}")
             if created_at_str: st.caption(f"Analyzed (raw): {created_at_str}")
             if updated_at_str: st.caption(f"Updated (raw): {updated_at_str}")

    if include_json_expander:
        with st.expander("🔍 View Raw JSON Response (Analysis Result)"):
            st.json(result)

st.title("🗣️ Meeting Analysis Application")

with st.sidebar:
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
                     st.warning("Session token may have expired. Refreshing...")
                     if not refresh_token():
                         st.error("Session expired. Please log in again.")
                         st.rerun()
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
                    if "login_user" in st.session_state: del st.session_state["login_user"]
                    if "login_pass" in st.session_state: del st.session_state["login_pass"]
                    st.rerun()
                else:
                    pass

if st.session_state.get('logged_in', False):

    tab_analysis, tab_history = st.tabs(["✨ New Analysis", "📂 History"])

    with tab_analysis:
        st.header("Submit New Transcript for Analysis")
        st.info("Submit transcript text or upload a file (.txt, .pdf). The app will extract the text (if applicable) and queue it for AI analysis using the direct processing endpoint.")

        with st.form("direct_submit_form", clear_on_submit=True):
            input_method = st.radio("Input Method", ["Paste Text", "Upload File"], index=0, key="direct_input_method", horizontal=True)
            raw_text_input = None
            uploaded_file_input = None

            if input_method == "Paste Text":
                raw_text_input = st.text_area("Paste Raw Transcript Text Here", height=300, key="direct_raw_text", help="Paste the full meeting transcript text.")
            else:
                uploaded_file_input = st.file_uploader(
                    "Choose a transcript file",
                    type=['txt', 'pdf'],
                    key="direct_file_upload",
                    help="Upload a text or PDF file containing the transcript."
                )
            submitted_direct = st.form_submit_button("🚀 Submit and Analyze")

        if submitted_direct:
            endpoint = "/analysis/process/direct/"
            form_data = None
            extracted_text = None
            has_valid_input = False

            if input_method == "Paste Text":
                if raw_text_input and raw_text_input.strip():
                    form_data = {'raw_text': raw_text_input}
                    st.write("Submitting provided raw text...")
                    has_valid_input = True
                else:
                    st.warning("Please paste some transcript text.")
                    has_valid_input = False

            elif input_method == "Upload File":
                if uploaded_file_input is not None:
                    try:
                        extracted_text = extract_text_from_uploaded_file(uploaded_file_input)
                        if extracted_text and extracted_text.strip():
                             st.success(f"Successfully extracted text from {uploaded_file_input.name} ({len(extracted_text):,} characters).")
                             form_data = {'raw_text': extracted_text}
                             has_valid_input = True
                        elif extracted_text is not None:
                             st.warning(f"File {uploaded_file_input.name} seems to contain no extractable text.")
                             has_valid_input = False
                        else:
                             has_valid_input = False
                    except Exception as e:
                         st.error(f"Error during file processing before submission: {e}")
                         has_valid_input = False
                else:
                    st.warning("Please upload a transcript file.")
                    has_valid_input = False

            if has_valid_input and form_data is not None:
                st.write("Sending extracted text to analysis API...")
                initial_response = make_request("POST", endpoint, data=form_data, files=None)

                if isinstance(initial_response, dict) and 'id' in initial_response and 'processing_status' in initial_response:
                    transcript_id = initial_response['id']
                    initial_status = initial_response['processing_status']
                    retrieved_meeting_id = initial_response.get('meeting_id')

                    st.success(f"✅ Submission successful! Transcript ID: **{transcript_id}**. Analysis queued.")
                    st.info(f"Initial Status: `{initial_status}`")
                    if retrieved_meeting_id: st.info(f"Associated Meeting ID: `{retrieved_meeting_id}`")

                    status_placeholder = st.status(f"Processing Transcript ID: {transcript_id}...", expanded=True)

                    max_attempts = 60
                    poll_interval = 5
                    attempts = 0
                    final_analysis_result = None
                    final_participants = None
                    polling_endpoint = f"/transcripts/status/{transcript_id}/"
                    analysis_endpoint = f"/analysis/transcript/{transcript_id}/"
                    current_status = initial_status

                    while attempts < max_attempts:
                        attempts += 1
                        time.sleep(poll_interval)

                        status_placeholder.write(f"Checking status... (Attempt {attempts}/{max_attempts})")
                        status_response = make_request("GET", polling_endpoint)

                        if isinstance(status_response, dict) and 'processing_status' in status_response:
                            current_status = status_response['processing_status']
                            if not retrieved_meeting_id: retrieved_meeting_id = status_response.get('meeting_id')

                            status_placeholder.update(label=f"Transcript {transcript_id} Status: **{current_status}**")

                            if current_status == "COMPLETED":
                                status_placeholder.write("Analysis completed! Fetching results...")
                                analysis_result = make_request("GET", analysis_endpoint)
                                if isinstance(analysis_result, dict):
                                    final_analysis_result = analysis_result
                                    status_placeholder.write("Analysis results received.")

                                    if retrieved_meeting_id:
                                        status_placeholder.write(f"Fetching details for Meeting ID: {retrieved_meeting_id}...")
                                        meeting_endpoint = f"/meetings/{retrieved_meeting_id}/"
                                        meeting_details = make_request("GET", meeting_endpoint)
                                        if isinstance(meeting_details, dict):
                                            final_participants = meeting_details.get('participants')
                                            status_placeholder.write("Meeting details (including participants) received.")
                                        else:
                                            status_placeholder.warning(f"Could not fetch meeting details for ID {retrieved_meeting_id}.")
                                    else:
                                         status_placeholder.warning("Could not determine meeting ID to fetch participants.")
                                    status_placeholder.update(label=f"Analysis for Transcript {transcript_id} Complete!", state="complete", expanded=False)
                                    st.success("📊 Processing complete. Results below:")
                                else:
                                    status_placeholder.error("Failed to fetch completed analysis results from API.")
                                    status_placeholder.update(label="Error fetching analysis results", state="error")
                                break

                            elif current_status == "FAILED":
                                error_msg = status_response.get('processing_error', 'Unknown processing error')
                                status_placeholder.error(f"Analysis Failed: {error_msg}")
                                status_placeholder.update(label=f"Analysis Failed for Transcript {transcript_id}", state="error")
                                break

                            elif current_status in ["PENDING", "PROCESSING"]:
                                pass
                            else:
                                status_placeholder.warning(f"Received unexpected status: {current_status}. Stopping poll.")
                                break

                        else:
                            status_placeholder.warning(f"Could not retrieve valid status update (Attempt {attempts}). Retrying...")
                            if attempts > 5 and status_response is None:
                                 status_placeholder.error("Failed to get status update after multiple attempts. Please check backend logs or history later.")
                                 status_placeholder.update(label="Status Check Failed", state="error")
                                 break

                    if attempts == max_attempts and current_status not in ["COMPLETED", "FAILED"]:
                        status_placeholder.warning("Polling timed out. Analysis might still be running or may have encountered an issue. Please check the history later or backend logs.")
                        status_placeholder.update(label="Polling Timeout", state="warning")

                    if final_analysis_result:
                        display_analysis_results(final_analysis_result, participants=final_participants)
                        if 'history_meetings_list' in st.session_state: del st.session_state['history_meetings_list']
                        if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']

                elif initial_response is None:
                    st.error("❌ Submission failed. Could not send data to API. Check connection or previous error messages.")
                else:
                    st.error(f"❌ Submission failed. Unexpected API response after sending data:")
                    try: st.json(initial_response)
                    except: st.write(initial_response)
            elif submitted_direct and not has_valid_input:
                 st.warning("No valid input provided (check text area or file upload/extraction). Submission cancelled.")

    with tab_history:
        st.header("View Past Analysis Results")

        col_load, col_select = st.columns([1, 3])

        with col_load:
             if st.button("🔄 Load Meeting History", key="load_history", use_container_width=True):
                  with st.spinner("Loading meetings..."):
                       meetings = make_request("GET", "/meetings/?limit=500")
                       if isinstance(meetings, list):
                           st.session_state.history_meetings_list = meetings
                           st.success(f"Loaded {len(meetings)} meetings.")
                           if not meetings: st.info("No past meetings found.")
                           if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']
                           if '_cached_analysis_meeting_id' in st.session_state: del st.session_state['_cached_analysis_meeting_id']
                           st.session_state.selected_meeting_id_history = None
                       else:
                           st.session_state.history_meetings_list = []
                           st.warning("Could not load meetings history. API error or no meetings found.")

        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list:
             meetings_list = st.session_state.history_meetings_list
             try:
                 sorted_meetings = sorted(meetings_list, key=lambda m: m.get('meeting_date', '1970-01-01T00:00:00Z'), reverse=True)
             except Exception as sort_e:
                 st.warning(f"Could not sort meetings by date: {sort_e}. Using received order.")
                 sorted_meetings = meetings_list

             meeting_options = {}
             for m in sorted_meetings:
                  meeting_id = m.get('id', 'N/A')
                  title = m.get('title', 'Untitled Meeting')
                  date_str = m.get('meeting_date', 'No Date')
                  try:
                      formatted_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M') if isinstance(date_str, str) else 'Invalid Date'
                  except: formatted_date = date_str
                  label = f"{title} (ID: {meeting_id} | {formatted_date})"
                  meeting_options[label] = meeting_id

             meeting_options_list = ["-- Select a Meeting --"] + list(meeting_options.keys())
             selected_id_from_state = st.session_state.get('selected_meeting_id_history')
             current_index = 0
             if selected_id_from_state:
                 try:
                     selected_label = next(label for label, id_val in meeting_options.items() if id_val == selected_id_from_state)
                     current_index = meeting_options_list.index(selected_label)
                 except (StopIteration, ValueError):
                     st.session_state.selected_meeting_id_history = None
                     current_index = 0

             with col_select:
                 selected_meeting_label = st.selectbox("Select Meeting to View Analysis", options=meeting_options_list,
                     index=current_index, key="history_meeting_select")

             selected_meeting_id = None
             if selected_meeting_label != "-- Select a Meeting --":
                 selected_meeting_id = meeting_options.get(selected_meeting_label)

             st.session_state.selected_meeting_id_history = selected_meeting_id

             if selected_meeting_id:
                 st.divider()
                 delete_col, title_col = st.columns([1, 5])

                 with title_col:
                     st.subheader(f"Analysis Results for: {selected_meeting_label}")

                 with delete_col:
                     delete_button_key = f"delete_init_{selected_meeting_id}"
                     confirm_delete_key = f"confirm_delete_{selected_meeting_id}"

                     if st.button("🗑️ Delete", key=delete_button_key, help="Delete this meeting and its associated transcripts/analyses."):
                         st.session_state[confirm_delete_key] = True
                         st.rerun()

                     if st.session_state.get(confirm_delete_key, False):
                         st.warning(f"**Confirm Deletion:** Are you sure you want to permanently delete meeting '{selected_meeting_label}'?")
                         confirm_col, cancel_col = st.columns(2)
                         with confirm_col:
                             if st.button("✅ Yes, Delete", key=f"delete_confirm_{selected_meeting_id}", use_container_width=True):
                                 with st.spinner(f"Deleting meeting {selected_meeting_id}..."):
                                     delete_endpoint = f"/meetings/{selected_meeting_id}/"
                                     delete_response = make_request("DELETE", delete_endpoint)

                                     if delete_response is True:
                                         st.success(f"Meeting {selected_meeting_id} deleted successfully.")
                                         st.session_state.history_meetings_list = [m for m in st.session_state.history_meetings_list if m.get('id') != selected_meeting_id]
                                         if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']
                                         if '_cached_analysis_meeting_id' in st.session_state: del st.session_state['_cached_analysis_meeting_id']
                                         st.session_state.selected_meeting_id_history = None
                                         # REMOVED -> st.session_state.history_meeting_select = "-- Select a Meeting --"
                                         del st.session_state[confirm_delete_key]
                                         st.rerun()
                                     else:
                                         st.error(f"Failed to delete meeting {selected_meeting_id}. See error details above.")
                                         del st.session_state[confirm_delete_key]
                                         st.rerun()
                         with cancel_col:
                              if st.button("❌ Cancel", key=f"delete_cancel_{selected_meeting_id}", use_container_width=True):
                                  del st.session_state[confirm_delete_key]
                                  st.rerun()

                 if not st.session_state.get(confirm_delete_key, False):
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
                                     st.info("No analysis results found for this meeting (may be pending, failed, or no transcripts submitted).")
                             else:
                                 st.warning(f"Could not load analysis results for meeting {selected_meeting_id}. API error or unexpected response.")
                                 st.session_state.selected_meeting_analyses = []
                                 st.session_state._cached_analysis_meeting_id = selected_meeting_id

                     if 'selected_meeting_analyses' in st.session_state and st.session_state.selected_meeting_analyses:
                         sorted_analyses = sorted(st.session_state.selected_meeting_analyses, key=lambda x: x.get('created_at', ''), reverse=True)

                         meeting_participants = None
                         if 'history_meetings_list' in st.session_state:
                             try:
                                 meeting_details = next(m for m in st.session_state.history_meetings_list if m.get('id') == selected_meeting_id)
                                 meeting_participants = meeting_details.get('participants')
                             except StopIteration:
                                 st.warning("Could not find meeting details in the loaded list to show participants.")

                         for analysis_result in sorted_analyses:
                             transcript_id = analysis_result.get('transcript_id', 'N/A')
                             created_time_str = analysis_result.get('created_at', 'N/A')
                             try:
                                 created_time_fmt = datetime.fromisoformat(created_time_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
                             except: created_time_fmt = created_time_str
                             expander_label = f"Analysis for Transcript ID: {transcript_id} (Created: {created_time_fmt})"

                             with st.expander(expander_label, expanded=True):
                                 display_analysis_results(analysis_result, participants=meeting_participants, include_json_expander=False)
                                 button_key = f"json_{transcript_id}_{created_time_str}"
                                 if st.button("Show Raw JSON", key=button_key):
                                     st.json(analysis_result)
                             st.markdown("---", unsafe_allow_html=True)

                     elif 'selected_meeting_analyses' in st.session_state and not st.session_state.selected_meeting_analyses:
                         pass
        elif 'history_meetings_list' in st.session_state and not st.session_state.history_meetings_list:
             st.info("No past meetings found in history after loading.")
        else:
             st.info("Click 'Load Meeting History' button above to view past analyses.")
elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar to access the application features.")