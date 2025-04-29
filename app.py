# app.py
import streamlit as st
import requests
import json
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Any
import io
import math
import traceback # For better error logging

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Meeting Analysis")

# --- Global Configuration & State Initialization ---
with st.sidebar:
    if "api_base_url" not in st.session_state:
        st.session_state.api_base_url = "http://127.0.0.1:8000/api"
    API_BASE_URL = st.text_input("API Base URL", key="api_base_url")

DEFAULT_ANALYSIS_LIMIT = 5

# --- Core Functions ---

def login(username, password):
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    try:
        response = requests.post(f"{api_base}/token/pair", json={"username": username, "password": password})
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]; st.session_state.refresh_token = token_data["refresh"]
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55)
        st.session_state.logged_in = True; st.session_state.username = username
        st.success("Login successful!")
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Login failed: {e}")
        if hasattr(e, 'response') and e.response:
            try: err = e.response.json().get("detail", "Unknown"); st.error(f"API Error: {err}")
            except: st.error(f"API Error: Status {e.response.status_code} - {e.response.text}")
        logout(silent=True); return False

def refresh_token():
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    if 'refresh_token' not in st.session_state: st.warning("No refresh token."); logout(); return False
    try:
        response = requests.post(f"{api_base}/token/refresh", json={"refresh": st.session_state.refresh_token})
        response.raise_for_status()
        token_data = response.json()
        st.session_state.access_token = token_data["access"]
        st.session_state.token_expiry = datetime.now() + timedelta(hours=23, minutes=55)
        st.session_state.logged_in = True
        st.info("Token refreshed.")
        return True
    except requests.exceptions.RequestException as e:
        st.warning("Session expired/invalid."); st.error(f"Refresh failed: {e}")
        if hasattr(e, 'response') and e.response and e.response.status_code in [401, 400]: st.error("Reason: Refresh token bad.")
        logout(); return False

def logout(silent=False):
    if not silent: st.info("Logging out...")
    keys_to_remove = [k for k in st.session_state if k != "api_base_url"]
    for key in keys_to_remove:
        try: del st.session_state[key]
        except KeyError: pass
    if not silent: st.success("Logged out.")

def ensure_authenticated():
    if not st.session_state.get('logged_in', False) or 'access_token' not in st.session_state: return False
    buffer = 60
    if 'token_expiry' not in st.session_state or datetime.now() >= (st.session_state.token_expiry - timedelta(seconds=buffer)):
        st.info("Token check: Refreshing...");
        if not refresh_token(): st.warning("Session expired."); st.rerun(); return False
    return True

def get_headers(include_content_type=True):
    if 'access_token' not in st.session_state: st.error("Auth token missing."); logout(); st.rerun(); return None
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    if include_content_type: headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers

def make_request(method, endpoint, json_data=None, data=None, files=None, params=None, timeout=30, **kwargs):
    api_base = st.session_state.get("api_base_url", "http://127.0.0.1:8000/api")
    if not ensure_authenticated(): return None
    include_content_type = json_data is not None and not files and not data
    headers = get_headers(include_content_type=include_content_type)
    if headers is None: return None
    req_params = params if params is not None else {}
    if method.upper() == 'GET' and json_data: req_params.update(json_data); json_data = None
    url = f"{api_base}{endpoint}"; attempt_retry = True
    while attempt_retry:
        attempt_retry = False
        try:
            response = requests.request( method, url, headers=headers, json=json_data, data=data, files=files, params=req_params, timeout=timeout, **kwargs )
            if response.status_code == 401:
                st.warning("Auth refresh needed...");
                if refresh_token(): headers = get_headers(include_content_type); attempt_retry = True; continue
                else: st.error("Refresh failed."); st.rerun(); return None
            response.raise_for_status()
            if response.status_code == 204: return True
            elif response.status_code in [200, 201, 202]:
                if response.text:
                    try: return response.json()
                    except json.JSONDecodeError: st.warning(f"API OK ({response.status_code}) non-JSON."); return response.text
                else: return True
            else: st.warning(f"Unexpected success {response.status_code}"); return response.text if response.text else True
        except requests.exceptions.HTTPError as e:
            st.error(f"HTTP Error: {e}" + (f" Status: {e.response.status_code}" if e.response else ""))
            if e.response:
                try:
                    err = e.response.json()
                    detail = err.get('detail', json.dumps(err))
                    if isinstance(detail, list):
                        detail = "; ".join(map(str, detail))
                    elif not isinstance(detail, str):
                        detail = json.dumps(detail)
                    st.error(f"Detail: {detail}")
                except json.JSONDecodeError:
                    st.error(f"Raw Error: {e.response.text[:500]}...")
            return None
        except requests.exceptions.ConnectionError as e: st.error(f"Connection Error: {e}"); return None
        except requests.exceptions.Timeout as e: st.error(f"Timeout: {e}"); return None
        except requests.exceptions.RequestException as e: st.error(f"Request Failed: {e}"); return None
        except Exception as e: st.error(f"Error in make_request: {e}"); st.error(traceback.format_exc()); return None
    return None

def display_analysis_results(result, participants: Optional[List[Any]] = None, include_json_expander=True):
    if not isinstance(result, dict): st.warning("Invalid result format."); st.json(result); return
    tx_id = result.get('transcript_id', 'N/A'); tx_title = result.get('transcript_title')
    st.markdown(f"**Tx ID:** `{tx_id}`" + (f" | **Title:** *{tx_title}*" if tx_title else ""))
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📝 Summary"); st.markdown(result.get('summary') or '_N/A_')
        st.subheader("📌 Key Points"); kp = result.get('key_points'); st.markdown("\n".join(f"- {p}" for p in kp) if kp else "_N/A_")
    with (c2):
        st.subheader("❗ Action Item"); task=result.get('task'); resp=result.get('responsible'); dl=result.get('deadline')
        if task or resp or dl:
            st.markdown(f"**Task:** {task or '_N/A_'}")
            st.markdown(f"**Responsible:** {resp or '_N/A_'}")
            dl_str = dl
            if dl:
                try:
                    deadline_dt = datetime.strptime(dl, "%Y-%m-%d").date()
                    dl_str = deadline_dt.strftime("%B %d, %Y")
                except (ValueError, TypeError):
                    st.warning(f"Bad deadline format: {dl}")
            st.markdown(f"**Deadline:** {dl_str or '_N/A_'}")
        else: st.info("No action item.")
        st.subheader("👥 Participants"); st.markdown(f"{', '.join(map(str, participants))}" if participants else "_N/A_")
        st.caption("---"); ts_c=result.get('created_at'); ts_u=result.get('updated_at'); dt_c=None
        try:
            if ts_c: dt_c=datetime.fromisoformat(str(ts_c).replace('Z','+00:00')); st.caption(f"Analyzed: {dt_c:%Y-%m-%d %H:%M}")
            if ts_u: dt_u=datetime.fromisoformat(str(ts_u).replace('Z','+00:00'));
            if dt_c is None or abs((dt_u-dt_c).total_seconds())>5: st.caption(f"Updated: {dt_u:%Y-%m-%d %H:%M}")
        except Exception as e: st.warning(f"TS parse error: {e}")
    if include_json_expander:
        with st.expander("🔍 View Raw JSON (Analysis)"): st.json(result)

# --- Main Application UI ---
st.title("🗣️ Meeting Analysis Application")

# --- Sidebar (Authentication) ---
with (st.sidebar):
    st.subheader("Authentication")
    if st.session_state.get('logged_in', False):
        st.success(f"Logged in: **{st.session_state.get('username', 'User')}**")
        if 'token_expiry' in st.session_state:
            try:
                rem=st.session_state.token_expiry-datetime.now()
                if rem.total_seconds() > 0:
                    st.info(f"Session ends in: {int(rem.total_seconds() // 60)}m")
                else:
                    st.warning("Session may have expired.")
            except Exception as e:
                st.warning(f"Token expiry display error: {e}")
        if st.button("Logout", key="logout_btn"): logout(); st.rerun()
    else:
        with st.form("login_form"):
            un=st.text_input("Username",key="li_u"); pw=st.text_input("Password",type="password",key="li_p")
            if st.form_submit_button("Login"):
                if login(un, pw): st.rerun()

# --- Main Content Area ---
if st.session_state.get('logged_in', False):

    # Initialize state keys
    for key, default in [ ('meeting_action', "Select Existing Meeting"), ('select_meeting_dropdown', "-- Select --"), ('history_filter_title', ""), ('history_filter_date_from', None), ('history_filter_date_to', None), ('analysis_results_offset', 0), ('analysis_results_limit', DEFAULT_ANALYSIS_LIMIT), ('analysis_results_total_count', 0), ('transcript_raw_text_cache', {}), ('history_meeting_select', "-- Select --"), ('selected_meeting_id_history', None), ]:
        if key not in st.session_state: st.session_state[key] = default

    just_created_meeting_id = st.session_state.pop('just_created_meeting_id', None)
    if just_created_meeting_id: st.session_state.meeting_action = "Select Existing Meeting"

    tab_analysis, tab_history = st.tabs(["✨ New Analysis", "📂 History"])

    # --- New Analysis Tab ---
    with tab_analysis:
        st.header("Submit New Transcript")
        st.subheader("Step 1: Select or Create Meeting")
        meeting_action = st.radio("Action", ["Select Existing Meeting", "Create New Meeting"], key="meeting_action", horizontal=True)
        selected_meeting_id = None; selected_meeting_title = None

        if st.session_state.meeting_action == "Select Existing Meeting":
            if 'analysis_tab_meetings_list' not in st.session_state:
                with st.spinner("Loading..."): meetings=make_request("GET","/meetings/?limit=500")
                st.session_state.analysis_tab_meetings_list=meetings if isinstance(meetings,list) else [];
                if not isinstance(meetings,list): st.warning("Mtg load fail.")
            meetings_list = st.session_state.get('analysis_tab_meetings_list', [])
            if meetings_list:
                try: sm=sorted(meetings_list, key=lambda m:m.get('meeting_date',''), reverse=True)
                except: sm=meetings_list
                opts={"-- Select --": None}; target_lbl=None
                for m in sm:
                    mid=m.get('id'); mt=m.get('title',''); mds=m.get('meeting_date','')
                    try: mdf=datetime.fromisoformat(mds.replace('Z','+00:00')).strftime('%y-%m-%d %H:%M') if mds else ''
                    except: mdf=mds;
                    label=f"{mt} ({mdf}) ID:{mid}"; opts[label]=mid
                    if just_created_meeting_id and mid == just_created_meeting_id: target_lbl=label
                opts_list=list(opts.keys()); s_idx=0
                if target_lbl:
                    try:
                        s_idx=opts_list.index(target_lbl)
                    except:
                        pass
                elif st.session_state.select_meeting_dropdown in opts_list:
                    try:
                        s_idx=opts_list.index(st.session_state.select_meeting_dropdown)
                    except:
                        pass
                sel_lbl=st.selectbox("Select Mtg",options=opts_list,index=s_idx,key="select_meeting_dropdown")
                selected_meeting_id=opts.get(sel_lbl)
                if selected_meeting_id: selected_meeting_title=sel_lbl.split(" (")[0]
            else: st.info("No meetings.")
        elif st.session_state.meeting_action == "Create New Meeting":
             with st.form("create_mtg_form"):
                nt=st.text_input("Mtg Title*",key="new_mtg_t_in")
                if st.form_submit_button("Create Mtg"):
                    if nt.strip():
                        with st.spinner("Creating..."): resp=make_request("POST","/meetings/",json_data={"title":nt})
                        if isinstance(resp,dict) and 'id' in resp:
                            st.success(f"Created '{resp.get('title')}'");
                            if 'analysis_tab_meetings_list' not in st.session_state: st.session_state.analysis_tab_meetings_list=[]
                            st.session_state.analysis_tab_meetings_list.append(resp)
                            st.session_state.just_created_meeting_id = resp['id']; st.rerun()
                        else: st.error("Create fail.")
                    else: st.warning("Title needed.")

        if selected_meeting_id: # Transcript Submission section
            st.divider(); st.subheader(f"Step 2: Add Txt to '{selected_meeting_title or f'ID:{selected_meeting_id}'}'")
            with st.form("tx_submit_form",clear_on_submit=True):
                im=st.radio("Input",["Paste","Upload"],key="tx_im",horizontal=True)
                txt_in=None; file_in=None
                if im=="Paste": txt_in=st.text_area("Paste Text",height=200,key="tx_raw_in")
                else: file_in=st.file_uploader("File",type=['txt','pdf','md','docx'],key="tx_file_in")
                if st.form_submit_button("🚀 Submit"):
                    init_resp=None; json_p=None; files_p=None; ep=None
                    if im=="Paste":
                        if txt_in and txt_in.strip(): ep=f"/transcripts/{selected_meeting_id}/"; json_p={'raw_text':txt_in};
                        else: st.warning("Paste text.")
                    elif im=="Upload":
                        if file_in: ep=f"/transcripts/{selected_meeting_id}/upload/"; files_p={'file':(file_in.name,file_in.getvalue(),file_in.type)};
                        else: st.warning("Upload file.")
                    if ep and (json_p or files_p):
                        with st.spinner("Submitting..."): init_resp=make_request("POST",ep,json_data=json_p,files=files_p)
                        if isinstance(init_resp,dict) and 'id' in init_resp:
                            tx_id=init_resp['id']; init_stat=init_resp['processing_status']; meet_id=init_resp.get('meeting_id')
                            st.success(f"✅ Submitted Tx ID:{tx_id}. Queued."); st.info(f"Status:{init_stat}")
                            ph=st.status(f"Processing {tx_id}...",expanded=True); max_att=60; poll_int=5; att=0; final_res=None; final_part=None; cur_stat=init_stat
                            while att<max_att:
                                att+=1; time.sleep(poll_int); ph.write(f"Checking({att})..."); stat_resp=make_request("GET",f"/transcripts/status/{tx_id}/")
                                if isinstance(stat_resp,dict) and 'processing_status' in stat_resp:
                                    cur_stat=stat_resp['processing_status'];
                                    if not meet_id: meet_id=stat_resp.get('meeting_id')
                                    ph.update(label=f"Tx {tx_id}:{cur_stat}")
                                    if cur_stat=="COMPLETED":
                                        ph.write("Fetching..."); anal_res=make_request("GET",f"/analysis/transcript/{tx_id}/")
                                        if isinstance(anal_res,dict):
                                            final_res=anal_res; ph.write("Results OK.")
                                            if meet_id: meet_dets=make_request("GET",f"/meetings/{meet_id}/"); final_part=meet_dets.get('participants') if isinstance(meet_dets,dict) else None
                                            ph.update(label="Complete!",state="complete",expanded=False); st.success("📊 Done.")
                                        else: st.error("Result fetch fail."); ph.error("Fetch fail.").update(label="Error",state="error")
                                        break
                                    elif cur_stat=="FAILED": ph.error(f"Failed:{stat_resp.get('processing_error','?')}"); ph.update(label="Failed",state="error"); break
                                    elif cur_stat in ["PENDING","PROCESSING"]: pass
                                    else: ph.warning(f"Bad status:{cur_stat}"); break
                                else: ph.warning(f"Status check fail({att}).");
                                if att>5 and stat_resp is None: ph.error("Status fail."); ph.update(label="Error",state="error"); break
                            if att==max_att and cur_stat not in ["COMPLETED","FAILED"]: ph.warning("Timeout."); ph.update(label="Timeout",state="warning")
                            if final_res: display_analysis_results(final_res,participants=final_part)
                            if 'history_meetings_list' in st.session_state: del st.session_state.history_meetings_list
                        elif init_resp is None: st.error("❌ Submit Fail. API?")
                        else: st.error("❌ Submit Fail."); st.json(init_resp)

        else: st.info("Select/Create meeting first.")


    # --- History Tab ---
    with tab_history:
        st.header("View History & Analysis")
        st.subheader("Filter Meetings")
        fc1,fc2,fc3=st.columns([2,1,1]); st.session_state.history_filter_title=fc1.text_input("Title:",key="hf_t",value=st.session_state.history_filter_title)
        st.session_state.history_filter_date_from=fc2.date_input("From:",key="hf_df",value=st.session_state.history_filter_date_from)
        st.session_state.history_filter_date_to=fc3.date_input("To:",key="hf_dt",value=st.session_state.history_filter_date_to)

        if st.button("🔄 Load / Filter History", key="load_h_btn", use_container_width=True):
            st.session_state.selected_meeting_id_history=None; st.session_state.analysis_results_offset=0; st.session_state.analysis_results_total_count=0
            if "history_meeting_select" in st.session_state: st.session_state.history_meeting_select="-- Select --"
            if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
            with st.spinner("Loading..."):
                params={'limit':500};
                if st.session_state.history_filter_title: params['title']=st.session_state.history_filter_title
                if st.session_state.history_filter_date_from: params['date_from']=st.session_state.history_filter_date_from.isoformat()
                if st.session_state.history_filter_date_to: params['date_to']=st.session_state.history_filter_date_to.isoformat()
                meetings=make_request("GET", "/meetings/", params=params)
                if isinstance(meetings, list): st.session_state.history_meetings_list=meetings; st.success(f"Loaded {len(meetings)}.")
                else: st.session_state.history_meetings_list=[]; st.warning("Load failed.")

        current_selected_meeting_id = None
        if 'history_meetings_list' in st.session_state and st.session_state.history_meetings_list:
            meetings_list=st.session_state.history_meetings_list
            try: sm=sorted(meetings_list, key=lambda m:m.get('meeting_date',''), reverse=True)
            except: sm=meetings_list
            opts={"-- Select --": None};
            for m in sm:
                mid=m.get('id'); mt=m.get('title',''); mds=m.get('meeting_date','')
                try: mdf=datetime.fromisoformat(mds.replace('Z','+00:00')).strftime('%y-%m-%d %H:%M') if mds else ''
                except: mdf=mds;
                label=f"{mt} ({mdf}) ID:{mid}"; opts[label]=mid
            opts_list=list(opts.keys()); sid=st.session_state.get('selected_meeting_id_history'); cidx=0
            if sid:
                try:
                    sl = next(l for l, i in opts.items() if i == sid)
                    cidx = opts_list.index(sl)
                except (StopIteration, ValueError):
                    st.session_state.selected_meeting_id_history=None

            sel_label=st.selectbox("Select Meeting",options=opts_list,index=cidx,key="history_meeting_select")
            current_selected_meeting_id = opts.get(sel_label)

            if st.session_state.get('selected_meeting_id_history') != current_selected_meeting_id:
                 st.session_state.analysis_results_offset=0; st.session_state.analysis_results_total_count=0
                 if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
                 if '_cached_analysis_meeting_id' in st.session_state: del st.session_state._cached_analysis_meeting_id
            st.session_state.selected_meeting_id_history = current_selected_meeting_id

            if current_selected_meeting_id:
                st.divider()
                del_col, title_col = st.columns([1,5]); title_col.subheader(f"Analyses for: {sel_label}")
                # *** CORRECTED DELETE CONFIRMATION LOGIC ***
                with del_col:
                    del_key=f"del_{current_selected_meeting_id}"; conf_key=f"conf_{current_selected_meeting_id}"
                    if st.button("🗑️",key=del_key,help="Delete Mtg"): st.session_state[conf_key]=True; st.rerun()

                    # Only show confirmation buttons if the key is True
                    if st.session_state.get(conf_key):
                        st.warning("Confirm?")
                        c1,c2 = st.columns(2) # Define columns INSIDE the if block
                        with c1:
                            if st.button("✅Yes",key=f"ok_{current_selected_meeting_id}"):
                                with st.spinner("Deleting..."): resp=make_request("DELETE",f"/meetings/{current_selected_meeting_id}/")
                                if conf_key in st.session_state: del st.session_state[conf_key] # Remove key FIRST
                                if resp is True:
                                    st.success("Deleted.")
                                    # Refresh meeting list state locally and reset selections
                                    if 'history_meetings_list' in st.session_state:
                                        st.session_state.history_meetings_list = [m for m in st.session_state.history_meetings_list if m.get('id') != current_selected_meeting_id]
                                    st.session_state.selected_meeting_id_history = None
                                    st.session_state.history_meeting_select = "-- Select --"
                                    if 'selected_meeting_analyses' in st.session_state: del st.session_state.selected_meeting_analyses
                                    if '_cached_analysis_meeting_id' in st.session_state: del st.session_state._cached_analysis_meeting_id
                                    st.rerun()
                                else:
                                    st.error("Failed.")
                                    st.rerun() # Rerun even on failure to clear confirmation
                        with c2:
                            if st.button("❌No",key=f"no_{current_selected_meeting_id}"):
                                if conf_key in st.session_state: del st.session_state[conf_key] # Remove key on cancel
                                st.rerun()
                # *** END CORRECTION ***

                # --- Fetch and Display Analysis (Only if NOT confirming delete) ---
                if not st.session_state.get(conf_key):
                    cached_mid = st.session_state.get('_cached_analysis_meeting_id')
                    if cached_mid != current_selected_meeting_id or 'selected_meeting_analyses' not in st.session_state:
                        anal_ep=f"/analysis/meeting/{current_selected_meeting_id}/"; anal_params={'offset':st.session_state.analysis_results_offset,'limit':st.session_state.analysis_results_limit}
                        with st.spinner("Fetching results..."): anal_resp=make_request("GET",anal_ep,params=anal_params)
                        results=[]; total=0
                        if isinstance(anal_resp,dict) and 'items' in anal_resp: results=anal_resp['items']; total=anal_resp['count']
                        elif anal_resp: st.warning("Bad analysis format.")
                        st.session_state.selected_meeting_analyses=results; st.session_state.analysis_results_total_count=total
                        st.session_state._cached_analysis_meeting_id=current_selected_meeting_id
                        if not results and anal_resp: st.info("No analysis results for this meeting.")

                    if 'selected_meeting_analyses' in st.session_state and st.session_state.selected_meeting_analyses:
                        analyses = st.session_state.selected_meeting_analyses; participants=None;
                        try: meeting=next(m for m in st.session_state.history_meetings_list if m.get('id')==current_selected_meeting_id); participants=meeting.get('participants')
                        except: pass
                        st.write(f"Displaying {len(analyses)} analysis result(s):")
                        for idx, analysis_result in enumerate(analyses):
                            tx_id = analysis_result.get('transcript_id', f'N/A_{idx}')
                            tx_title = analysis_result.get('transcript_title')
                            exp_label = f"Analysis for Tx ID: {tx_id}" + (f' - "{tx_title}"' if tx_title else "")
                            with st.expander(exp_label, expanded=True):
                                display_analysis_results(analysis_result, participants=participants, include_json_expander=False)
                                raw_text_visible_key = f"raw_text_visible_{tx_id}"
                                if raw_text_visible_key not in st.session_state: st.session_state[raw_text_visible_key] = False
                                if st.button("Show/Hide Raw Tx", key=f"btn_raw_{tx_id}"):
                                    st.session_state[raw_text_visible_key] = not st.session_state[raw_text_visible_key]
                                if st.session_state[raw_text_visible_key]:
                                    raw_text = st.session_state.transcript_raw_text_cache.get(tx_id)
                                    if raw_text is None: # Fetch if not cached
                                        with st.spinner(f"Loading raw text (Tx {tx_id})..."):
                                            tx_details = make_request("GET", f"/transcripts/{tx_id}/")
                                            if isinstance(tx_details, dict): raw_text = tx_details.get('raw_text') or "_Not found_"
                                            else: raw_text = "_Error loading_"
                                            st.session_state.transcript_raw_text_cache[tx_id] = raw_text # Cache result
                                    st.text_area(f"Raw Text (Tx {tx_id})", value=raw_text, height=200, disabled=True, key=f"text_area_raw_{tx_id}")
                            st.markdown("---")

                        total=st.session_state.analysis_results_total_count; limit=st.session_state.analysis_results_limit; offset=st.session_state.analysis_results_offset
                        total_p=math.ceil(total/limit); curr_p=(offset//limit)+1
                        if total_p > 1:
                            st.write("---"); nc1,nc2,nc3 = st.columns([1,2,1])
                            if nc1.button("⬅️ Prev", key="prev_a", disabled=(curr_p<=1)): st.session_state.analysis_results_offset=max(0,offset-limit); st.rerun()
                            nc2.markdown(f"<p style='text-align: center;'>Page {curr_p}/{total_p} ({total})</p>", unsafe_allow_html=True)
                            if nc3.button("Next ➡️", key="next_a", disabled=(curr_p>=total_p)): st.session_state.analysis_results_offset=offset+limit; st.rerun()

        elif 'history_meetings_list' in st.session_state: st.info("No meetings match filters.")

# --- Footer or Initial Message ---
elif not st.session_state.get('logged_in', False):
    st.info("👋 Welcome! Please log in using the sidebar.")