# File: dashboard/dashboard.py (Enhanced UI Version)

import streamlit as st
import pandas as pd
import requests
import os
import time
from streamlit_option_menu import option_menu
from zoneinfo import ZoneInfo
import streamlit.components.v1 as components
from streamlit import cache_data
from streamlit_js_eval import streamlit_js_eval
from sqlalchemy import create_engine

# --- 1. Configuration ---
st.set_page_config(page_title="Incident Monitoring", layout="wide")
FLASK_SERVER_URL = "http://127.0.0.1:5000"
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
database_path = os.path.join(project_dir, 'database', 'incidents.db')
engine = create_engine(f'sqlite:///{database_path}')

# --- 2. Custom CSS ---
def load_css():
    st.markdown("""
        <style>
            .main { background-color: #0E1117; color: #FAFAFA; }
            header, footer { visibility: hidden; }
            .block-container { padding-top: 1rem; padding-bottom: 2rem; }
            .row-text { color: #D3D3D3; font-size: 16px; padding-top: 25px; text-align: center; }
            .stButton>button { width: 100%; border-radius: 5px; }

            /* --- ENHANCED TOAST NOTIFICATION STYLES --- */
            .toast-container { position: fixed; top: 70px; right: 20px; z-index: 9999; }
            .toast {
                background-color: #262730; color: #FAFAFA; padding: 16px 24px; margin-bottom: 10px;
                border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.25);
                display: flex; align-items: center; border-left: 8px solid #ccc;
                width: 360px; /* Slightly wider */
                animation: slideIn 0.5s forwards, fadeOut 0.5s 6.5s forwards;
            }
            .toast-icon {
                font-size: 32px; /* Larger icon */
                margin-right: 20px;
                line-height: 1;
            }
            .toast-content strong { font-size: 1.1em; }

            /* Color coding for severity in border and title */
            .toast.high { border-left-color: #f44336; }
            .toast.high .toast-title { color: #f44336; }

            .toast.medium { border-left-color: #ff9800; }
            .toast.medium .toast-title { color: #ff9800; }

            .toast.low { border-left-color: #4CAF50; }
            .toast.low .toast-title { color: #4CAF50; }

            @keyframes slideIn { from { transform: translateX(110%); } to { transform: translateX(0); } }
            @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; transform: translateX(110%);} }
        </style>
    """, unsafe_allow_html=True)

load_css()

# --- 3. Helper Functions ---
@st.cache_data(ttl=5)
def get_data_from_db(query):
    try:
        df = pd.read_sql(query, engine)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception as e:
        st.error(f"Could not connect to SQLite DB. Error: {e}")
        return pd.DataFrame()

def update_incident_status(incident_id, new_status):
    with st.spinner(f'Processing Incident {incident_id}...'):
        try:
            requests.post(f"{FLASK_SERVER_URL}/api/update_status/{incident_id}", json={'status': new_status})
            st.toast(f"Incident {incident_id} updated to '{new_status}'!")
            st.cache_data.clear()
        except requests.exceptions.ConnectionError:
            st.error("Connection to backend failed.")
    st.rerun()

def websocket_and_toast_component():
    audio_file_url = f"{FLASK_SERVER_URL}/static/alert.mp3"
    components.html(f"""
        <audio id="alert-sound" src="{audio_file_url}" preload="auto"></audio>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
        <script>
            function ensureToastContainer() {{
                if (!window.parent.document.getElementById('toast-container-main')) {{
                    const mainContainer = window.parent.document.createElement('div');
                    mainContainer.id = 'toast-container-main';
                    mainContainer.className = 'toast-container';
                    window.parent.document.body.appendChild(mainContainer);
                }}
            }}
            ensureToastContainer();

            window.primeAudio = function() {{
                var audio = document.getElementById('alert-sound');
                audio.play().then(() => {{ audio.pause(); audio.currentTime = 0; }}).catch(e => {{}});
            }};

            function showToast(severity, location, time) {{
                const container = window.parent.document.getElementById('toast-container-main');
                if (!container) return;
                const toast = document.createElement('div');
                toast.className = `toast ${{severity.toLowerCase()}}`;
                let icon = 'ℹ️';
                if (severity.toLowerCase() === 'high') icon = '🚨';
                if (severity.toLowerCase() === 'medium') icon = '⚠️';
                if (severity.toLowerCase() === 'low') icon = '✅';
                
                // --- ENHANCED TOAST INNER HTML ---
                toast.innerHTML = `
                    <div class="toast-icon">${{icon}}</div>
                    <div class="toast-content">
                        <strong class="toast-title">New Incident: ${{(severity || '').toUpperCase()}}</strong><br>
                        Location: ${{location || 'N/A'}} at ${{time || ''}}
                    </div>
                `;
                container.appendChild(toast);
                setTimeout(() => {{ toast.remove(); }}, 7000);
            }}

            if (!window.socket) {{
                window.socket = io.connect('{FLASK_SERVER_URL}');
                window.socket.on('new_incident', function(data) {{
                    showToast(data.severity, data.location, data.time);
                    document.getElementById('alert-sound').play().catch(e => console.warn("Audio play failed."));
                    window.parent.postMessage({{isStreamlitMessage: true, type: "SET_VALUE", key: "new_incident_trigger", value: Date.now()}}, "*");
                }});
            }}
        </script>
    """, height=0)

    return streamlit_js_eval(js_expressions="window.stVariable", key="new_incident_trigger")

def display_incident_row(row, index, show_actions=True):
    # Base columns that are always shown
    col_widths = [0.05, 0.25, 0.1, 0.1, 0.1, 0.15, 0.1]
    if show_actions:
        # Add widths for the action buttons
        col_widths.extend([0.075, 0.075])
    
    cols = st.columns(col_widths)
    
    # --- Display common data ---
    cols[0].markdown(f"<div class='row-text'>{index + 1}</div>", unsafe_allow_html=True)
    if 'video_clip_path' in row and row['video_clip_path']:
        cols[1].video(f"{FLASK_SERVER_URL}/clips/{row['video_clip_path']}")
    utc_time = pd.to_datetime(row['timestamp']); ist_time = utc_time.tz_localize('UTC').astimezone(ZoneInfo("Asia/Kolkata"))
    cols[2].markdown(f"<div class='row-text'>{ist_time.strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
    cols[3].markdown(f"<div class='row-text'>{ist_time.strftime('%H:%M:%S')}</div>", unsafe_allow_html=True)
    cols[4].markdown(f"<div class='row-text'>{row.get('severity', 'N/A').capitalize()}</div>", unsafe_allow_html=True)
    cols[5].markdown(f"<div class='row-text'>{row.get('camera_ip', 'N/A')}</div>", unsafe_allow_html=True)
    cols[6].markdown(f"<div class='row-text'>{row.get('location', 'N/A')}</div>", unsafe_allow_html=True)
    
    # --- ENHANCEMENT: Conditionally show action buttons ---
    if show_actions:
        incident_id = row['id']
        if row['status'] == 'New':
            if cols[7].button("Verify", key=f"v_{incident_id}"): update_incident_status(incident_id, 'Confirmed')
            if cols[8].button("Delete", key=f"d_{incident_id}"): update_incident_status(incident_id, 'Dismissed')
        elif row['status'] == 'Alert Sent':
            if cols[7].button("Confirm", key=f"c_{incident_id}"): update_incident_status(incident_id, 'Confirmed')
            if cols[8].button("Revert", key=f"a_{incident_id}", type="primary"): update_incident_status(incident_id, 'Aborted')

# --- ENHANCEMENT: Header function now supports conditional action columns ---
def show_table_header(show_actions=True):
    headers = ["No", "Image", "Date", "Time", "Severity", "MAC Address", "Location"]
    col_widths = [0.05, 0.25, 0.1, 0.1, 0.1, 0.15, 0.1]
    
    if show_actions:
        headers.extend(["Verify", "Delete"])
        col_widths.extend([0.075, 0.075])

    cols = st.columns(col_widths)
    for col, header in zip(cols, headers):
        col.markdown(f"**{header}**")
    st.markdown("<hr style='margin-top: 0px; margin-bottom: 10px;'>", unsafe_allow_html=True)

# --- 4. Initialize Session State ---
if 'nav_selection' not in st.session_state:
    st.session_state.nav_selection = "Home"
if 'last_known_incident_timestamp' not in st.session_state:
    st.session_state.last_known_incident_timestamp = None

# --- 5. Main UI Layout ---
with st.container():
    col_nav, col_sound, col_search = st.columns([8, 1, 3])
    with col_nav:
        selected = option_menu(
            menu_title=None,
            options=["Home", "Verified", "Deleted", "History"],
            icons=["house-fill", "check-circle-fill", "trash-fill", "clock-history"],
            orientation="horizontal",
            default_index=["Home", "Verified", "Deleted", "History"].index(st.session_state.nav_selection),
            styles={"container": {"background-color": "transparent", "padding": "0!important"}, "nav-link": {"color": "#C9D1D9"}, "nav-link-selected": {"background-color": "#007BFF"}}
        )
    with col_sound:
        if st.button("🔊", help="Click here once to enable sound alerts."):
            streamlit_js_eval(js_function="window.primeAudio")
            st.toast("Sound enabled!", icon="🔊")
    with col_search:
        st.text_input("Search", key="search", placeholder="Search incidents...", label_visibility="collapsed")

st.markdown("---") # Visual separator

# --- 6. Page Display Logic ---
if selected == "Home":
    st.subheader("🚨 Incidents Awaiting Review")
    df = get_data_from_db("SELECT * FROM incident WHERE status IN ('New', 'Alert Sent') ORDER BY timestamp DESC")
    if df.empty:
        st.success("All clear! No incidents awaiting review.")
    else:
        show_table_header(show_actions=True)
        for index, row in df.iterrows():
            display_incident_row(row, index, show_actions=True)

elif selected == "Verified":
    st.subheader("✅ Verified Incidents")
    df = get_data_from_db("SELECT * FROM incident WHERE status = 'Confirmed' ORDER BY timestamp DESC")
    if df.empty: st.info("No incidents have been verified yet.")
    else:
        show_table_header(show_actions=False) # Hide action headers
        for index, row in df.iterrows():
            display_incident_row(row, index, show_actions=False) # Hide action buttons

elif selected == "Deleted":
    st.subheader("🗑️ Deleted / Dismissed Incidents")
    df = get_data_from_db("SELECT * FROM incident WHERE status IN ('Dismissed', 'Aborted') ORDER BY timestamp DESC")
    if df.empty: st.info("No incidents have been deleted.")
    else:
        show_table_header(show_actions=False) # Hide action headers
        for index, row in df.iterrows():
            display_incident_row(row, index, show_actions=False) # Hide action buttons

elif selected == "History":
    st.subheader("📜 Complete Incident History Log")
    df_history = get_data_from_db("SELECT * FROM incident ORDER BY timestamp DESC")
    if df_history.empty:
        st.info("No history to display.")
    else:
        if 'timestamp' in df_history.columns:
            df_history['timestamp'] = pd.to_datetime(df_history['timestamp']).dt.tz_localize('UTC').dt.tz_convert(ZoneInfo("Asia/Kolkata"))
        st.dataframe(df_history[['timestamp', 'severity', 'location', 'status', 'camera_ip']], use_container_width=True)

# --- 7. Final, Robust Trigger Logic for Auto-Refresh ---
new_incident_timestamp = websocket_and_toast_component()
if new_incident_timestamp and (new_incident_timestamp != st.session_state.last_known_incident_timestamp):
    st.session_state.last_known_incident_timestamp = new_incident_timestamp
    st.cache_data.clear() # IMPORTANT: Clear cache before rerunning
    st.rerun()