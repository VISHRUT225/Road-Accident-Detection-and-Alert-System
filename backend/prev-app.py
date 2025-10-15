# File: backend/app.py (Final Version with Twilio SSL Fix and SQLite)

import os
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask_socketio import SocketIO
from twilio.rest import Client
from dotenv import load_dotenv

# --- THIS IS THE FIX (Part 1): Import libraries to disable SSL verification ---
import ssl
from twilio.http.http_client import TwilioHttpClient
# --------------------------------------------------------------------------

# Load environment variables from a .env file (optional, for secure credential handling)
load_dotenv() 

# --- TWILIO CONFIGURATION ---
# For your presentation, you've hardcoded these. This is fine for a local demo.
# Using a .env file is the recommended practice for security.
TWILIO_ACCOUNT_SID = "AC7d912d68ea59fe04f3f8698e1b05"
TWILIO_AUTH_TOKEN = "7a55629b8a495b9a09a224c56c14a7b2"
TWILIO_PHONE_NUMBER = "+18144586781"
DESTINATION_NUMBER = "+916355741383"
# --------------------------------------------------------------------------

# --- Setup Paths ---
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
clips_dir = os.path.join(project_dir, 'clips')
static_dir = os.path.join(project_dir, 'backend', 'static')
database_path = os.path.join(project_dir, 'database', 'incidents.db')
app = Flask(__name__)

# --- Configure for SQLite ---
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{database_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- THIS IS THE FIX (Part 2): Create a custom HTTP client that bypasses SSL verification ---
# This is necessary for running behind a corporate firewall that inspects SSL traffic.
# WARNING: Do not use this in a real, public-facing production environment without understanding the security risks.
if os.environ.get("FLASK_ENV") != "production": # A safety check
    ssl._create_default_https_context = ssl._create_unverified_context
    proxy_client = TwilioHttpClient()
    proxy_client.session.verify = False
    # Initialize Twilio Client using our custom client
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, http_client=proxy_client)
else:
    # In a real production environment, use the default secure client
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
# -----------------------------------------------------------------------------------------

# --- SQLAlchemy Database Model ---
class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    location = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(50), nullable=False)
    video_clip_path = db.Column(db.String(200))
    camera_ip = db.Column(db.String(50))
    status = db.Column(db.String(50), nullable=False, default='New')

# --- Reusable function to send SMS ---
def send_alert_sms(body):
    """Sends an SMS using the configured Twilio client."""
    if not twilio_client or not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, DESTINATION_NUMBER]):
        print("--- TWILIO WARNING: Credentials missing or incomplete. SMS was NOT sent. ---")
        return False
    try:
        message = twilio_client.messages.create(
            to=DESTINATION_NUMBER, 
            from_=TWILIO_PHONE_NUMBER,
            body=body
        )
        print(f"✓ TWILIO SUCCESS: Message SID {message.sid} sent to {DESTINATION_NUMBER}")
        return True
    except Exception as e:
        print(f"✗ TWILIO ERROR: Failed to send SMS. Exception: {e}")
        return False

# --- API Endpoint for New Incidents ---
@app.route('/api/report_incident', methods=['POST'])
def report_incident():
    data = request.get_json();
    if not data: return jsonify({'error': 'Missing data'}), 400
    
    new_status = 'New'
    severity = data.get('severity', '').lower()
    
    if severity == 'high':
        new_status = 'Alert Sent'
        ist_now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
        sms_body = (f"!!! URGENT ACCIDENT ALERT (HIGH) !!!\n"
                    f"Location: {data.get('location', 'N/A')}\n"
                    f"Time (IST): {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
        send_alert_sms(sms_body)
    
    new_incident = Incident(
        location=data['location'], severity=data['severity'],
        video_clip_path=data.get('video_clip_path'), camera_ip=data.get('camera_ip'),
        status=new_status
    )
    db.session.add(new_incident)
    db.session.commit()

    socketio.emit('new_incident', {'message': 'A new incident reported!'})
    return jsonify({'message': 'Incident reported', 'id': new_incident.id}), 201

# --- API Endpoint for Supervisor Actions ---
@app.route('/api/update_status/<int:incident_id>', methods=['POST'])
def update_status(incident_id):
    data = request.get_json(); new_status = data.get('status')
    
    incident = db.session.get(Incident, incident_id)
    if not incident: abort(404)
    
    original_status = incident.status
    incident.status = new_status
    db.session.commit()
        
    if new_status == 'Aborted' and original_status == 'Alert Sent':
        sms_body = (f"!!! ABORT ALERT !!!\n"
                    f"FALSE ALARM: Disregard previous alert for location: {incident.location}")
        send_alert_sms(sms_body)
    elif new_status == 'Confirmed' and original_status == 'New':
        ist_time = incident.timestamp.astimezone(ZoneInfo("Asia/Kolkata"))
        sms_body = (f"CONFIRMED ACCIDENT ({incident.severity.upper()})\n"
                    f"Location: {incident.location}\n"
                    f"Time (IST): {ist_time.strftime('%Y-%m-%d %H:%M:%S')}")
        send_alert_sms(sms_body)
    
    return jsonify({'message': f'Incident {incident_id} updated to {new_status}'})

@app.route('/clips/<path:filename>')
def serve_clip(filename): return send_from_directory(clips_dir, filename)

@app.route('/static/<path:filename>')
def serve_static(filename): return send_from_directory(static_dir, filename)

if __name__ == '__main__':
    # Create the database and tables if they don't exist
    with app.app_context():
        db.create_all()
    print("Starting Flask-SocketIO server with SQLite database...")
    socketio.run(app, debug=True, port=5000)