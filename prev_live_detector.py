# live_detector.py
# A self-contained script for live accident detection from a webcam.

import cv2
import time
import os
from collections import deque, defaultdict
from datetime import datetime
import torch
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import numpy as np
from itertools import combinations
import timm
from ultralytics import YOLO
import supervision as sv
from safetensors.torch import load_file as load_safetensors

# --- 1. Configuration ---
FINE_TUNED_MODEL_PATH = "vit_severity_model_best.pth"
PRETRAINED_VIT_PATH = "model.safetensors"
YOLO_MODEL_PATH = "yolov10m.pt" 

CLIP_LENGTH = 32
INFERENCE_INTERVAL = 15
ALERT_COOLDOWN = 10
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CLASS_NAMES = ['no_crash', 'low', 'medium', 'high']

# --- 2. Model Architecture (No changes here) ---
class VisionTransformerAccidentDetector(nn.Module):
    def __init__(self, num_features, num_classes, hidden_size=256, dropout=0.5):
        super(VisionTransformerAccidentDetector, self).__init__()
        self.base_model = timm.create_model('vit_tiny_patch16_224', pretrained=False, num_classes=0, global_pool='avg')
        num_video_features = self.base_model.num_features
        self.video_gru = nn.GRU(input_size=num_video_features, hidden_size=hidden_size, batch_first=True)
        self.feature_gru = nn.GRU(input_size=num_features, hidden_size=hidden_size // 4, batch_first=True)
        self.classifier = nn.Sequential(nn.Linear(hidden_size + hidden_size // 4, 512), nn.ReLU(), nn.Dropout(dropout), nn.Linear(512, num_classes))
    def forward(self, video_input, feature_input):
        batch_size, clip_len, C, H, W = video_input.shape
        video_input_reshaped = video_input.view(batch_size * clip_len, C, H, W)
        video_features = self.base_model(video_input_reshaped)
        video_features_seq = video_features.view(batch_size, clip_len, -1)
        _, video_hidden = self.video_gru(video_features_seq)
        _, feature_hidden = self.feature_gru(feature_input)
        video_hidden = video_hidden.squeeze(0); feature_hidden = feature_hidden.squeeze(0)
        fused = torch.cat((video_hidden, feature_hidden), dim=1)
        return self.classifier(fused)

# --- 3. Helper Functions (No changes here) ---
def load_model(fine_tuned_path, pretrained_base_path):
    print(f"Loading model for inference on {DEVICE}...")
    model = VisionTransformerAccidentDetector(num_features=3, num_classes=4)
    print(f"  - Loading base ViT weights from: {pretrained_base_path}")
    base_weights = load_safetensors(pretrained_base_path, device=DEVICE.type)
    model.load_state_dict(base_weights, strict=False)
    print(f"  - Loading your fine-tuned weights from: {fine_tuned_path}")
    state_dict = torch.load(fine_tuned_path, map_location=DEVICE)
    if next(iter(state_dict)).startswith('module.'):
        from collections import OrderedDict
        new_state_dict = OrderedDict()
        for k, v in state_dict.items(): new_state_dict[k[7:]] = v
        model.load_state_dict(new_state_dict)
    else:
        model.load_state_dict(state_dict)
    model.to(DEVICE)
    model.eval()
    print("✓ Model loaded successfully.")
    return model

def preprocess_frames(frames):
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    processed = []
    for frame in frames:
        frame_resized = cv2.resize(frame, (224, 224))
        rgb_frame = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_frame)
        processed.append(transform(pil_image))
    return torch.stack(processed).unsqueeze(0).to(DEVICE)

# --- 4. Main Execution Block ---
if __name__ == '__main__':
    required_files = [FINE_TUNED_MODEL_PATH, PRETRAINED_VIT_PATH, YOLO_MODEL_PATH]
    if not all(os.path.exists(p) for p in required_files):
        print("--- FATAL ERROR: A required model file is missing! ---")
        for f in required_files: print(f"  - {f} {'(FOUND)' if os.path.exists(f) else '(MISSING)'}")
        exit()

    accident_model = load_model(FINE_TUNED_MODEL_PATH, PRETRAINED_VIT_PATH)
    yolo_detector = YOLO(YOLO_MODEL_PATH)
    
    # We no longer need a separate tracker object from supervision
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_thickness=2, text_scale=1)
    frames_buffer = deque(maxlen=CLIP_LENGTH)
    tracking_history = deque(maxlen=CLIP_LENGTH)
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): print("FATAL ERROR: Could not open webcam."); exit()

    frame_count, last_alert_time = 0, 0
    print("\n--- Live Detection Started ---")

    while True:
        ret, frame = cap.read()
        if not ret: break
        frames_buffer.append(frame)

        # --- THIS IS THE FIX ---
        # Use the YOLO model's built-in .track() method, just like in your training script.
        # persist=True tells the tracker to remember objects between frames.
        results = yolo_detector.track(frame, tracker="botsort.yaml", persist=True, verbose=False)[0]
        # ----------------------
        
        # Convert the results to supervision's format for easy handling and visualization
        detections = sv.Detections.from_ultralytics(results)
        # If the tracker loses all objects, results.boxes.id can be None. We handle this.
        if results.boxes.id is not None:
            detections.tracker_id = results.boxes.id.cpu().numpy().astype(int)
        
        tracking_history.append(detections)
        
        if frame_count % INFERENCE_INTERVAL == 0 and len(frames_buffer) == CLIP_LENGTH:
            all_frame_features = []
            for dets in tracking_history:
                frame_max_iou = 0
                if len(dets.xyxy) > 1:
                    for box1, box2 in combinations(dets.xyxy, 2):
                        iou = sv.box_iou_batch(np.array([box1]), np.array([box2]))[0][0]
                        frame_max_iou = max(frame_max_iou, iou)
                all_frame_features.append([0, frame_max_iou, 0])
            
            video_tensor = preprocess_frames(list(frames_buffer))
            feature_tensor = torch.tensor(all_frame_features, dtype=torch.float32).unsqueeze(0).to(DEVICE)
            
            with torch.no_grad():
                outputs = accident_model(video_tensor, feature_tensor)
                prediction = torch.max(outputs, 1)[1].item()
            
            if prediction > 0 and (time.time() - last_alert_time > ALERT_COOLDOWN):
                severity = CLASS_NAMES[prediction]
                print("\n" + "="*50); print(f"!!! ACCIDENT DETECTED !!!")
                print(f"    - Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    - Predicted Severity: {severity.upper()}"); print("="*50 + "\n")
                last_alert_time = time.time()
        
        # Annotation logic
        annotated_frame = box_annotator.annotate(frame.copy(), detections)
        # Check if there are any tracked objects before trying to create labels
        if detections.tracker_id is not None:
            labels = [f"#{tracker_id} {results.names[class_id].upper()}" for tracker_id, class_id in zip(detections.tracker_id, detections.class_id)]
            annotated_frame = label_annotator.annotate(annotated_frame, detections, labels)
        
        if time.time() - last_alert_time < ALERT_COOLDOWN:
            cv2.putText(annotated_frame, "COOLDOWN", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)

        cv2.imshow('Live Accident Detection - Press "q" to Quit', annotated_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'): break
        frame_count += 1

    cap.release(); cv2.destroyAllWindows()
    print("--- Detection Stopped ---")