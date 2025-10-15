# config.py

# --- Kaggle Directory Paths ---
VIDEO_INPUT_DIR = "/kaggle/input/acc-sample-50/"
OUTPUT_DIR = "/kaggle/working/output/"

# --- Stage 1: Tracking Output ---
TRACKING_OUTPUT_DIR = f"{OUTPUT_DIR}/tracking_data/"

# --- Stage 5 & 6: Model Paths ---
# Use YOLOv10 Medium model
YOLO_MODEL_PATH = 'yolov10m.pt' 
# The final trained model will be saved here
SAVED_MODEL_PATH = f"{OUTPUT_DIR}/3d_cnn_accident_detector.pth"

# --- Data Processing Parameters ---
CLIP_LENGTH = 32          # Frames per clip
IMAGE_SIZE = (224, 224)   # H, W for the model

# --- Training Parameters ---
# Use a smaller batch size for 3D-CNNs due to higher memory usage
BATCH_SIZE = 4            
EPOCHS = 50
LEARNING_RATE = 0.0003
PATIENCE = 10             # For early stopping