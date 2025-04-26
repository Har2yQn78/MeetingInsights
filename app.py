import streamlit as st
import requests
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Any
import io
import fitz

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
        st.session_state.token_expiry = datetime.now() + timedelta(hours=5)
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
        st.session_state.token_expiry = datetime.now() + timedelta(hours=5)
        st.session_state.logged_in = True
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Session expired or token invalid. Please log in again.")
        st.error(f"Token refresh failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 401:
             st.error("Reason: Refresh token is invalid or has expired.")
        logout()
        return False

def logout():
    keys_to_remove = list(st.session_state.keys())
    st.info("Logging out...")
    for key in keys_to_remove:
        del st.session_state[key]

def ensure_authenticated():
    if not st.session_state.get('logged_in', False) or 'access_token' not in st.session_state:
        return False

    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=15)):
        st.info("Access token nearing expiry or expired, attempting refresh...")
        if not refresh_token():
            st.warning("Session expired. Please log in again.")
            return False
        else:
            st.info("Token refreshed successfully.")
    return True

def get_headers(include_content_type=True):
    if 'access_token' not in st.session_state:
         st.error("Authentication token missing unexpectedly. Please log in.")
         return None
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers

def make_request(method, endpoint, json_data=None, data=None, files=None, timeout=30, **kwargs):
    if not ensure_authenticated():
        st.warning("Authentication required. Please log in.")
        st.stop()
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
            st.warning("Received 401 Unauthorized. Attempting refresh...")
            if refresh_token():
                headers = get_headers(include_content_type=include_content_type)
                if headers is None: return None
                st.info("Retrying request with refreshed token...")
                response = requests.request(method, url, headers=headers, json=json_data, data=data, files=files, timeout=timeout, **kwargs)
                if response.status_code == 401:
                    st.error("Authentication still failed after refresh. Check permissions or log in again.")
                    logout()
                    st.rerun()
                    return None
            else:
                st.error("Token refresh failed during retry. Please log in again.")
                st.rerun()
                return None

        response.raise_for_status()

        if response.status_code == 204: return True
        elif response.status_code == 202:
            st.info(f"Request accepted by API (Status {response.status_code}). Background processing started.")
            try: return response.json()
            except json.JSONDecodeError: return True
        elif response.text:
            try: return response.json()
            except json.JSONDecodeError:
                st.warning(f"API returned status {response.status_code} but response is not valid JSON.")
                st.text(response.text[:500] + "...")
                return response.text
        else: return True

    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP Error: {http_err}")
        if http_err.response is not None:
            st.error(f"Status Code: {http_err.response.status_code}")
            try:
                error_detail = http_err.response.json()
                detail_msg = error_detail.get('detail', json.dumps(error_detail))
                st.error(f"API Error Detail: {detail_msg}")
            except json.JSONDecodeError:
                st.error("Raw Error Response:"); st.text(http_err.response.text)
        return None
    except requests.exceptions.ConnectionError as conn_err:
        st.error(f"Connection Error: Failed to connect to API at {API_BASE_URL}. Is the server running?"); st.error(f"Details: {conn_err}")
        return None
    except requests.exceptions.Timeout as timeout_err:
        st.error(f"Request Timed Out: The API server did not respond in {timeout} seconds."); st.error(f"Details: {timeout_err}")
        return None
    except requests.exceptions.RequestException as req_err:
        st.error(f"Request Failed: An unexpected error occurred during the request."); st.error(f"Details: {req_err}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred in make_request function: {e}")
        import traceback; st.error(traceback.format_exc())
        return None

def extract_text_from_pdf(file_content: bytes) -> str:
    try:
        with fitz.open(stream=file_content, filetype="pdf") as doc:
            text = ""
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        raise ValueError(f"Could not process PDF file: {e}")

def extract_text_from_txt(file_content: bytes) -> str:
    try:
        return file_content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return file_content.decode('latin-1')
        except Exception as e:
            st.error(f"Error decoding text file (tried UTF-8, Latin-1): {e}")
            raise ValueError("Could not decode text file. Ensure it's UTF-8 or Latin-1 encoded.")
    except Exception as e:
        st.error(f"Error reading text file: {e}")
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
        st.error(f"An unexpected error occurred during text extraction: {e}")
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
             st.markdown(f"**Deadline:** {deadline if deadline else '_Not specified_'}")
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
        elif participants:
            st.markdown(f"{participants}")
        else:
            st.markdown("_Not available for this analysis._")

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
                if created_dt is None or abs((updated_dt - created_dt).total_seconds()) > 1:
                     st.caption(f"Updated: {updated_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except (ValueError, TypeError):
             if created_at_str: st.caption(f"Analyzed: {created_at_str}")
             if updated_at_str: st.caption(f"Updated: {updated_at_str}")

    if include_json_expander:
        with st.expander("🔍 View Raw JSON Response (Analysis Result)"):
            st.json(result)


st.title("🗣️ Meeting Analysis Application")

with st.sidebar:
    st.subheader("Authentication")
    if st.session_state.get('logged_in', False):
        st.success(f"Logged in as {st.session_state.get('username', 'User')}")
        if 'token_expiry' in st.session_state:
             try:
                 now = datetime.now()
                 expiry = st.session_state.token_expiry
                 remaining = expiry - now
                 if remaining.total_seconds() > 0:
                     total_seconds = int(remaining.total_seconds())
                     days, rem = divmod(total_seconds, 86400); hrs, rem = divmod(rem, 3600); mins, secs = divmod(rem, 60)
                     expiry_str = f"{mins}m {secs}s"
                     if hrs > 0: expiry_str = f"{hrs}h {expiry_str}"
                     if days > 0: expiry_str = f"{days}d {expiry_str}"
                     st.info(f"Session expires in: {expiry_str.strip()}")
                 else:
                     st.warning("Session token has expired. Refreshing...")
                     if not refresh_token(): st.error("Session expired. Please log in again."); st.rerun()
             except Exception as e: st.warning(f"Could not display token expiry: {e}")

        if st.button("Logout"):
            logout(); st.rerun()
    else:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Login")
            if submitted:
                if login(username, password): st.rerun()

if st.session_state.get('logged_in', False):

    tab_analysis, tab_history = st.tabs(["✨ New Analysis", "📂 History"])

    with tab_analysis:
        st.header("Submit New Transcript for Analysis")
        st.info("Submit transcript text or upload a file (.txt, .pdf). The app will extract the text and queue it for AI analysis.")

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
                    help="Upload a text, PDF, or Markdown file containing the transcript."
                )
            submitted_direct = st.form_submit_button("🚀 Submit and Analyze")

        if submitted_direct:
            endpoint = "/analysis/process/direct/"
            form_data = None
            extracted_text = None
            has_input = False

            if input_method == "Paste Text":
                if raw_text_input and raw_text_input.strip():
                    form_data = {'raw_text': raw_text_input}
                    st.write("Submitting provided raw text..."); has_input = True
                else: st.warning("Please paste some transcript text.")

            elif input_method == "Upload File":
                if uploaded_file_input is not None:
                    try:
                        extracted_text = extract_text_from_uploaded_file(uploaded_file_input)
                        if extracted_text and extracted_text.strip():
                             st.success(f"Successfully extracted text from {uploaded_file_input.name} ({len(extracted_text)} characters).")
                             form_data = {'raw_text': extracted_text}
                             has_input = True
                        elif extracted_text is not None:
                             st.warning(f"File {uploaded_file_input.name} seems to contain no text after extraction.")
                             has_input = False
                        else:
                             has_input = False
                    except Exception as e:
                         st.error(f"Error during file processing: {e}")
                         has_input = False
                else:
                    st.warning("Please upload a transcript file.")

            if has_input and form_data is not None:
                st.write("Sending extracted text to analysis API...")
                initial_response = make_request("POST", endpoint, data=form_data, files=None)

                if isinstance(initial_response, dict) and 'id' in initial_response and 'processing_status' in initial_response:
                    transcript_id = initial_response['id']
                    initial_status = initial_response['processing_status']
                    retrieved_meeting_id = initial_response.get('meeting_id')

                    st.success(f"✅ Submission successful! Transcript ID: {transcript_id}. Analysis queued.")
                    st.info(f"Initial Status: {initial_status}")

                    status_placeholder = st.status(f"Processing Transcript ID: {transcript_id}...", expanded=True)

                    max_attempts = 60
                    attempts = 0
                    final_analysis_result = None
                    final_participants = None
                    polling_endpoint = f"/transcripts/status/{transcript_id}/"
                    analysis_endpoint = f"/analysis/transcript/{transcript_id}/"
                    current_status = initial_status

                    while attempts < max_attempts:
                        attempts += 1
                        time.sleep(5)

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
                                    status_placeholder.write("Analysis results received. Fetching meeting details...")

                                    if retrieved_meeting_id:
                                        meeting_endpoint = f"/meetings/{retrieved_meeting_id}/"
                                        meeting_details = make_request("GET", meeting_endpoint)
                                        if isinstance(meeting_details, dict):
                                            final_participants = meeting_details.get('participants')
                                            status_placeholder.write("Meeting details received.")
                                        else:
                                            status_placeholder.warning(f"Could not fetch meeting details for ID {retrieved_meeting_id}.")
                                    else:
                                         status_placeholder.warning("Could not determine meeting ID to fetch participants.")

                                    status_placeholder.update(label=f"Analysis for Transcript {transcript_id} Complete!", state="complete", expanded=False)
                                    st.success("📊 Processing complete:")
                                else:
                                    status_placeholder.error("Failed to fetch completed analysis results.")
                                    status_placeholder.update(label="Error fetching analysis results", state="error")
                                break

                            elif current_status == "FAILED":
                                error_msg = status_response.get('processing_error', 'Unknown error')
                                status_placeholder.error(f"Analysis Failed: {error_msg}")
                                status_placeholder.update(label=f"Analysis Failed for Transcript {transcript_id}", state="error")
                                break

                            elif current_status in ["PENDING", "PROCESSING"]:
                                pass
                            else:
                                status_placeholder.warning(f"Unexpected status: {current_status}")
                                break

                        else:
                            status_placeholder.warning(f"Could not retrieve valid status (Attempt {attempts}). Retrying...")
                            if attempts > 5 and status_response is None:
                                 status_placeholder.error("Failed to get status update after multiple attempts. Please check backend logs.")
                                 status_placeholder.update(label="Status Check Failed", state="error")
                                 break

                    if attempts == max_attempts and not final_analysis_result and current_status not in ["COMPLETED", "FAILED"]:
                        status_placeholder.warning("Polling timed out. Analysis might still be running, have failed without updating, or the task may not have started. Please check the analysis history later or backend logs.")
                        status_placeholder.update(label="Polling Timeout", state="warning")

                    if final_analysis_result:
                        display_analysis_results(final_analysis_result, participants=final_participants)
                        if 'history_meetings_list' in st.session_state: del st.session_state['history_meetings_list']
                        if 'selected_meeting_analyses' in st.session_state: del st.session_state['selected_meeting_analyses']

                elif initial_response is None:
                    st.error("❌ Submission failed. Could not send data to API. Check connection or previous error messages.")
                else:
                    st.error(f"❌ Submission failed. Unexpected API response after sending data: {initial_response}")
            elif submitted_direct and not has_input:
                 st.warning("No valid input provided (check text area or file upload/extraction).")


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
                           if 'history_meeting_select' in st.session_state: st.session_state.history_meeting_select = "-- Select a Meeting --"
                       else:
                           st.session_state.history_meetings_list = []
                           st.warning("Could not load meetings history. API error or no meetings.")

        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list:
             meetings_list = st.session_state.history_meetings_list
             try:
                 sorted_meetings = sorted(meetings_list, key=lambda m: m.get('meeting_date', '1970-01-01T00:00:00Z'), reverse=True)
             except Exception as sort_e:
                 st.warning(f"Could not sort meetings by date: {sort_e}. Using received order."); sorted_meetings = meetings_list

             meeting_options = {}
             for m in sorted_meetings:
                  meeting_id = m.get('id', 'N/A'); title = m.get('title', 'Untitled'); date_str = m.get('meeting_date', 'No Date')
                  try:
                      formatted_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M') if isinstance(date_str, str) else 'Invalid Date'
                  except: formatted_date = date_str
                  label = f"{title} (ID: {meeting_id} | {formatted_date})"
                  meeting_options[label] = meeting_id

             meeting_options_list = ["-- Select a Meeting --"] + list(meeting_options.keys())

             selected_id_from_state = st.session_state.get('selected_meeting_id_history'); current_index = 0
             if selected_id_from_state:
                 try:
                     selected_label = next(label for label, id_val in meeting_options.items() if id_val == selected_id_from_state)
                     current_index = meeting_options_list.index(selected_label)
                 except (StopIteration, ValueError): st.session_state.selected_meeting_id_history = None

             with col_select:
                 selected_meeting_label = st.selectbox("Select Meeting to View Analysis", options=meeting_options_list, index=current_index, key="history_meeting_select")

             selected_meeting_id = None
             if selected_meeting_label != "-- Select a Meeting --": selected_meeting_id = meeting_options.get(selected_meeting_label)
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
                             if not analysis_results_list: st.info("No analysis results found for this meeting (may be pending/failed).")
                         else:
                             st.warning(f"Could not load analysis results for meeting {selected_meeting_id}. API error?"); st.session_state.selected_meeting_analyses = []; st.session_state._cached_analysis_meeting_id = selected_meeting_id

                 if 'selected_meeting_analyses' in st.session_state and st.session_state.selected_meeting_analyses:
                     sorted_analyses = sorted(st.session_state.selected_meeting_analyses, key=lambda x: x.get('created_at', ''), reverse=True)

                     for analysis_result in sorted_analyses:
                         transcript_id = analysis_result.get('transcript_id', 'N/A'); created_time_str = analysis_result.get('created_at', 'N/A')
                         try: created_time_fmt = datetime.fromisoformat(created_time_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
                         except: created_time_fmt = created_time_str
                         expander_label = f"Analysis for Transcript ID: {transcript_id} (Created: {created_time_fmt})"

                         with st.expander(expander_label, expanded=True):
                            meeting_participants = None
                            if 'history_meetings_list' in st.session_state:
                                try:
                                    meeting_details = next(m for m in st.session_state.history_meetings_list if m.get('id') == selected_meeting_id)
                                    meeting_participants = meeting_details.get('participants')
                                except StopIteration: pass

                            display_analysis_results(analysis_result, participants=meeting_participants, include_json_expander=False)
                            button_key = f"json_{transcript_id}_{created_time_str}"
                            if st.button("Show Raw JSON", key=button_key): st.json(analysis_result)
                         st.markdown("---")

                 elif 'selected_meeting_analyses' in st.session_state and not st.session_state.selected_meeting_analyses: pass

        elif 'history_meetings_list' in st.session_state and not st.session_state.history_meetings_list:
             st.info("No past meetings found in history after loading.")
        else:
             st.info("Click 'Load Meeting History' button above to view past analyses.")


elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar to access the application features.")
    st.image("https://streamlit.io/images/brand/streamlit-logo-secondary-colormark-darktext.png", width=300)