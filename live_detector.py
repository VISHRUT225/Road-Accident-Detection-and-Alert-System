# live_detector.py (FINAL Enhanced Version: Non-Blocking & Refactored)

import cv2
import time
import os
import shutil
from collections import deque, defaultdict
from datetime import datetime
import torch
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import numpy as np
from itertools import combinations
import timm
import requests
from ultralytics import YOLO
import supervision as sv
from safetensors.torch import load_file as load_safetensors
from model import VisionTransformerAccidentDetector
from zoneinfo import ZoneInfo
import ffmpeg
import argparse
import threading # --- ENHANCEMENT: Import threading for non-blocking network calls ---

# --- 1. Configuration ---
FINE_TUNED_MODEL_PATH = "vit_severity_model_best.pth"
PRETRAINED_VIT_PATH = "model.safetensors"
YOLO_MODEL_PATH = "yolov10m.pt"
CLIP_LENGTH, INFERENCE_INTERVAL, ALERT_COOLDOWN = 32, 15, 20
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CLASS_NAMES = ['no_crash', 'low', 'medium', 'high']
API_URL = "http://127.0.0.1:5000/api/report_incident"
CAMERA_ID, LOCATION, CAMERA_IP = "VIDEO_FILE", "Local Test", "127.0.0.1" # Default values
CONFIDENCE_THRESHOLD = 0.80

# --- 2. Helper Functions ---

# --- ENHANCEMENT: Non-blocking function to send alerts ---
def send_alert_to_backend(payload):
    """Sends the incident report to the backend in a separate thread."""
    try:
        response = requests.post(API_URL, json=payload, timeout=10) # Added a timeout
        if response.status_code == 201:
            print("✓ Backend received the alert successfully.")
        else:
            print(f"✗ Backend responded with an error: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Error: Could not connect to backend. {e}")

# --- ENHANCEMENT: Abstracted feature calculation logic ---
def calculate_kinematic_features(tracking_history):
    """
    Analyzes object paths to calculate kinematic features like deceleration,
    IoU, and direction change for each frame in the history buffer.
    """
    object_paths = defaultdict(list)
    for f_idx, tracked_dets in enumerate(tracking_history):
        if tracked_dets.tracker_id is not None:
            for tracker_id, box in zip(tracked_dets.tracker_id, tracked_dets.xyxy):
                x_center, y_center = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                object_paths[tracker_id].append({'frame': f_idx, 'center': np.array([x_center, y_center])})

    all_frame_features = []
    for f_idx, tracked_dets in enumerate(tracking_history):
        frame_decelerations, frame_dir_changes, frame_max_iou = [0.0], [0.0], 0.0
        if len(tracked_dets.xyxy) > 1:
            for box1, box2 in combinations(tracked_dets.xyxy, 2):
                iou = sv.box_iou_batch(np.array([box1]), np.array([box2]))[0][0]
                frame_max_iou = max(frame_max_iou, iou)

        if tracked_dets.tracker_id is not None:
            for tracker_id in tracked_dets.tracker_id:
                path = [p['center'] for p in object_paths[tracker_id] if p['frame'] <= f_idx]
                if len(path) >= 3:
                    p1, p2, p3 = path[-3], path[-2], path[-1]
                    v1, v2 = np.linalg.norm(p2 - p1), np.linalg.norm(p3 - p2)
                    frame_decelerations.append(v1 - v2)
                    vec1, vec2 = p2 - p1, p3 - p2
                    norm_prod = np.linalg.norm(vec1) * np.linalg.norm(vec2)
                    if norm_prod > 0:
                        angle = np.degrees(np.arccos(np.clip(np.dot(vec1, vec2) / norm_prod, -1.0, 1.0)))
                        frame_dir_changes.append(angle)

        all_frame_features.append([max(frame_decelerations), frame_max_iou, max(frame_dir_changes)])
    return all_frame_features

def load_model(fine_tuned_path, pretrained_base_path):
    print(f"Loading model for inference on {DEVICE}...")
    model = VisionTransformerAccidentDetector(num_features=3, num_classes=4)
    model.load_state_dict(load_safetensors(pretrained_base_path, device=DEVICE.type), strict=False)
    state_dict = torch.load(fine_tuned_path, map_location=DEVICE)
    if next(iter(state_dict)).startswith('module.'):
        from collections import OrderedDict
        new_state_dict = OrderedDict()
        for k, v in state_dict.items(): new_state_dict[k[7:]] = v
        model.load_state_dict(new_state_dict)
    else: model.load_state_dict(state_dict)
    model.to(DEVICE); model.eval()
    print("✓ Model loaded successfully.")
    return model

def preprocess_frames(frames):
    transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])
    processed = [transform(Image.fromarray(cv2.cvtColor(cv2.resize(f, (224, 224)), cv2.COLOR_BGR2RGB))) for f in frames]
    return torch.stack(processed).unsqueeze(0).to(DEVICE)

# --- 3. Main Execution Block ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Live Accident Detection from Webcam or Video File.")
    parser.add_argument('--video_path', type=str, default=None, help="Path to a video file. Uses webcam if not provided.")
    args = parser.parse_args()

    required_files = [FINE_TUNED_MODEL_PATH, PRETRAINED_VIT_PATH, YOLO_MODEL_PATH]
    if not all(os.path.exists(p) for p in required_files):
        print("--- FATAL ERROR: A required model file is missing! ---")
        for f in required_files: print(f"  - {f} {'(FOUND)' if os.path.exists(f) else '(MISSING)'}")
        exit()

    accident_model, yolo_detector = load_model(FINE_TUNED_MODEL_PATH, PRETRAINED_VIT_PATH), YOLO(YOLO_MODEL_PATH)
    box_annotator, label_annotator = sv.BoxAnnotator(thickness=2), sv.LabelAnnotator(text_thickness=2, text_scale=1)
    frames_buffer, tracking_history = deque(maxlen=CLIP_LENGTH), deque(maxlen=CLIP_LENGTH)

    if args.video_path:
        if not os.path.exists(args.video_path):
            print(f"FATAL ERROR: Video file not found at '{args.video_path}'"); exit()
        source = args.video_path
        print(f"\n--- Processing video file: {source} ---")
    else:
        source = 0; CAMERA_ID = "WEBCAM_01"
        print("\n--- Starting detection from live webcam feed ---")

    cap = cv2.VideoCapture(source)
    if not cap.isOpened(): print(f"FATAL ERROR: Could not open video source: {source}"); exit()

    frame_count, last_alert_time = 0, 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("--- End of video file or webcam disconnected. ---"); break

        frames_buffer.append(frame)
        results = yolo_detector.track(frame, tracker="botsort.yaml", persist=True, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(results)
        if results.boxes.id is not None: detections.tracker_id = results.boxes.id.cpu().numpy().astype(int)
        tracking_history.append(detections)

        if frame_count % INFERENCE_INTERVAL == 0 and len(frames_buffer) == CLIP_LENGTH:
            # 1. Calculate features using the refactored helper function
            all_frame_features = calculate_kinematic_features(tracking_history)

            # 2. Preprocess video and feature tensors
            video_tensor = preprocess_frames(list(frames_buffer))
            feature_tensor = torch.tensor(all_frame_features, dtype=torch.float32).unsqueeze(0).to(DEVICE)

            with torch.no_grad():
                outputs = accident_model(video_tensor, feature_tensor)
                probabilities = torch.nn.functional.softmax(outputs, dim=1)
                confidence, prediction = torch.max(probabilities, 1)
                confidence, prediction = confidence.item(), prediction.item()

            if (prediction > 0 and confidence >= CONFIDENCE_THRESHOLD and time.time() - last_alert_time > ALERT_COOLDOWN):
                severity = CLASS_NAMES[prediction]
                ist_now = datetime.now(ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata"))
                print("\n" + "="*50); print(f"!!! ACCIDENT DETECTED (CONFIDENCE: {confidence:.2f}) !!!")
                print(f"    - Timestamp: {ist_now.strftime('%Y-%m-%d %H:%M:%S')} IST")
                print(f"    - Predicted Severity: {severity.upper()}"); print("="*50 + "\n")
                last_alert_time = time.time()

                temp_dir = 'temp_frames'
                os.makedirs(temp_dir, exist_ok=True)
                for i, f in enumerate(list(frames_buffer)):
                    cv2.imwrite(os.path.join(temp_dir, f'frame_{i:03d}.png'), f)
                clip_filename = f"incident_{CAMERA_ID}_{ist_now.strftime('%Y%m%d_%H%M%S')}.mp4"
                clip_path_on_disk = os.path.join('clips', clip_filename)
                try:
                    (ffmpeg.input(os.path.join(temp_dir, 'frame_%03d.png'), framerate=10)
                     .output(clip_path_on_disk, vcodec='libx264', pix_fmt='yuv420p')
                     .run(capture_stdout=True, capture_stderr=True, overwrite_output=True))
                    print(f"✓ Video clip saved successfully to: {clip_path_on_disk}")

                    payload = {"location": LOCATION, "severity": severity, "camera_ip": CAMERA_IP, "video_clip_path": clip_filename}
                    
                    # --- ENHANCEMENT: Non-blocking network call ---
                    # The main loop continues immediately without waiting for the request to complete.
                    alert_thread = threading.Thread(target=send_alert_to_backend, args=(payload,))
                    alert_thread.start()

                except ffmpeg.Error as e: print(f"--- FFMPEG ERROR --- \n{e.stderr.decode()}\n--- END FFMPEG ERROR ---")
                # --- ENHANCEMENT: Resilient cleanup block ---
                finally:
                    # Retry logic to prevent crash if ffmpeg is slow to release file lock
                    for i in range(5): # Try up to 5 times
                        try:
                            shutil.rmtree(temp_dir)
                            break # Success, exit the loop
                        except PermissionError:
                            print(f"Cleanup warning: temp_dir is locked. Retrying in 0.1s... (Attempt {i+1}/5)")
                            time.sleep(0.1)
                        except Exception as e:
                            print(f"An unexpected error occurred during cleanup: {e}")
                            break

        annotated_frame = box_annotator.annotate(frame.copy(), detections)
        if detections.tracker_id is not None:
            labels = [f"#{tid} {results.names[cid]}" for tid, cid in zip(detections.tracker_id, detections.class_id)]
            annotated_frame = label_annotator.annotate(annotated_frame, detections, labels)
        if time.time() - last_alert_time < ALERT_COOLDOWN: cv2.putText(annotated_frame, "COOLDOWN", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        cv2.imshow('Live Accident Detection', annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'): break
        frame_count += 1

    cap.release(); cv2.destroyAllWindows()
    print("\n--- Detection Stopped ---")