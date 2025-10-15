# test_alert.py
import requests
import json

# The URL of your Flask API endpoint
api_url = "http://127.0.0.1:5000/api/report_incident"

# --- Simulate a HIGH severity incident ---
high_severity_data = {
    "location": "Main St & 1st Ave",
    "severity": "high",
    "camera_ip": "192.168.1.101",
    "video_clip_path": None # Add a path to a real .mp4 file if you have one
}

# --- Simulate a MEDIUM severity incident ---
medium_severity_data = {
    "location": "Oak St & 2nd Ave",
    "severity": "medium",
    "camera_ip": "192.168.1.102",
    "video_clip_path": None
}

# Send the HIGH severity alert
print("Sending HIGH severity alert...")
response = requests.post(api_url, json=high_severity_data)
print(f"Response: {response.status_code}, {response.json()}")

# Send the MEDIUM severity alert
print("\nSending MEDIUM severity alert...")
response = requests.post(api_url, json=medium_severity_data)
print(f"Response: {response.status_code}, {response.json()}")