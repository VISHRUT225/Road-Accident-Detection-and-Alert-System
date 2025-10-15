# File: backend/app.py (Enhanced Version)

import os
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask_socketio import SocketIO
import smtplib
import ssl
from email.message import EmailMessage
import threading
# --- GMAIL CONFIGURATION (Recommendation: Use Environment Variables) ---
SENDER_EMAIL = os.environ.get("GMAIL_SENDER", "vdpatel22556@gmail.com")
SENDER_APP_PASSWORD = os.environ.get("GMAIL_PASSWORD", "tcrqpjunzjsxrhey")
RECIPIENT_EMAIL = os.environ.get("GMAIL_RECIPIENT", "Patelvishrutku.Dineshbhai@ltimindtree.com")

# --- Setup Paths and SQLite DB ---
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
clips_dir = os.path.join(project_dir, 'clips')
static_dir = os.path.join(project_dir, 'backend', 'static')
database_path = os.path.join(project_dir, 'database', 'incidents.db')
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{database_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- SQLAlchemy Database Model ---
class Incident(db.Model):
    # ... (model is unchanged) ...
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    location = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(50), nullable=False)
    video_clip_path = db.Column(db.String(200))
    camera_ip = db.Column(db.String(50))
    status = db.Column(db.String(50), nullable=False, default='New')

# --- NEW: Function to run email sending in a background thread ---
def send_email_in_background(subject, body):
    """Creates and starts a new thread to send an email without blocking."""
    email_thread = threading.Thread(target=send_alert_email, args=(subject, body))
    email_thread.start()


# --- Email Sending Function (unchanged) ---
def send_alert_email(subject, body):
    # ... (function is unchanged) ...
    if not all([SENDER_EMAIL, SENDER_APP_PASSWORD, RECIPIENT_EMAIL]):
        print("--- GMAIL WARNING: Credentials not found. Email was NOT sent. ---")
        return False
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as smtp:
            smtp.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"✓ GMAIL SUCCESS: Alert email sent to {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        print(f"✗ GMAIL ERROR: Failed to send email. Exception: {e}")
        return False

# --- REFACTORED SECTION START ---

# --- Service Function for Creating a New Incident ---
def handle_new_incident(data):
    """Contains all logic for reporting a new incident."""
    # Centralized and safe data access
    location = data.get('location', 'Unknown Location')
    severity = data.get('severity', 'normal').lower()
    
    new_status = 'New'
    if severity == 'high':
        new_status = 'Alert Sent'
        ist_now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
        subject = f"URGENT ACCIDENT ALERT: HIGH Severity"
        body = (f"!!! URGENT ACCIDENT ALERT (HIGH) !!!\n"
                f"Location: {location}\n"
                f"Time (IST): {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
        send_email_in_background(subject, body)
    
    new_incident = Incident(
        location=location,
        severity=data.get('severity', 'normal'), # Use original case for DB
        video_clip_path=data.get('video_clip_path'),
        camera_ip=data.get('camera_ip'),
        status=new_status
    )
    db.session.add(new_incident)
    db.session.commit()

    # Emit WebSocket event after commit
    ist_time = new_incident.timestamp.astimezone(ZoneInfo("Asia/Kolkata"))
    socketio.emit('new_incident', {
        'id': new_incident.id,
        'severity': new_incident.severity,
        'location': new_incident.location,
        'time': ist_time.strftime('%H:%M:%S')
    })
    
    return new_incident

# --- Service Function for Updating an Incident Status ---
# --- Service Function for Updating an Incident Status (MODIFIED) ---
def handle_status_update(incident, new_status, original_status):
    """Contains all logic for handling status-change side-effects like emails."""
    subject = None
    body = None

    if new_status == 'Aborted' and original_status == 'Alert Sent':
        print("DEBUG: Condition MET for 'Aborted' email. Attempting to send...")
        subject = f"ABORT ALERT: False Alarm at {incident.location}"
        body = (f"!!! ABORT ALERT !!!\n"
                f"FALSE ALARM: Disregard previous alert for location: {incident.location}")
    
    elif new_status == 'Confirmed' and original_status == 'New':
        print("DEBUG: Condition MET for 'Confirmed' email. Attempting to send...")
        ist_time = incident.timestamp.astimezone(ZoneInfo("Asia/Kolkata"))
        subject = f"CONFIRMED ACCIDENT: {incident.severity.upper()} Severity"
        body = (f"CONFIRMED ACCIDENT ({incident.severity.upper()})\n"
                f"Location: {incident.location}\n"
                f"Time (IST): {ist_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    
    # If a subject and body were created, send the email in the background
    if subject and body:
        send_email_in_background(subject, body) # --- THIS IS THE KEY CHANGE ---
    else:
        print(f"DEBUG: No email condition met for new_status='{new_status}' and original_status='{original_status}'. No email sent.")

# --- API Endpoints (Now cleaner and call service functions) ---
@app.route('/api/report_incident', methods=['POST'])
def report_incident():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing data'}), 400
    
    # Delegate all logic to the service function
    new_incident = handle_new_incident(data)
    
    return jsonify({'message': 'Incident reported', 'id': new_incident.id}), 201

@app.route('/api/update_status/<int:incident_id>', methods=['POST'])
def update_status(incident_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({'error': 'Missing status field'}), 400

    incident = db.session.get(Incident, incident_id)
    if not incident:
        abort(404)
    
    original_status = incident.status
    
    # Delegate email logic to the service function BEFORE committing the change
    handle_status_update(incident, new_status, original_status)
    
    # Now update and commit the change to the database
    incident.status = new_status
    db.session.commit()
    
    return jsonify({'message': f'Incident {incident_id} updated to {new_status}'})

# --- REFACTORED SECTION END ---

@app.route('/clips/<path:filename>')
def serve_clip(filename): return send_from_directory(clips_dir, filename)

@app.route('/static/<path:filename>')
def serve_static(filename): return send_from_directory(static_dir, filename)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    print("Starting Flask-SocketIO server with SQLite database...")
    socketio.run(app, debug=True, use_reloader=False, port=5000, allow_unsafe_werkzeug=True)