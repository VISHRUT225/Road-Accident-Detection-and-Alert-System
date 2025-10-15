# step_3_interactive_labeler.py (Run this locally)
import pandas as pd
from pathlib import Path

# --- CONFIGURE THESE PATHS ON YOUR LOCAL MACHINE ---
# Use Path for better cross-platform compatibility
DOWNLOADS_DIR = Path.home() / "C:/Users/T8544/Project_accident/acc-sample-50/" # Or wherever you downloaded the files
PREDICTIONS_PATH = DOWNLOADS_DIR / "acc-predicted_events.csv"
MASTER_LABELS_OUTPUT_PATH = DOWNLOADS_DIR / "acc-master_ground_truth_events.csv"
# ----------------------------------------------------

def main_interactive_labeler():
    if not PREDICTIONS_PATH.exists():
        print(f"FATAL: Predictions file not found at {PREDICTIONS_PATH}")
        return
        
    predictions_df = pd.read_csv(PREDICTIONS_PATH)
    
    # --- Load existing labels to enable resume functionality ---
    if MASTER_LABELS_OUTPUT_PATH.exists():
        try:
            master_labels_df = pd.read_csv(MASTER_LABELS_OUTPUT_PATH)
            print(f"Resuming session. Loaded {len(master_labels_df)} previously labeled clips.")
        except pd.errors.EmptyDataError:
            master_labels_df = pd.DataFrame(columns=['clip_name', 'event_start_frame', 'event_end_frame', 'severity'])
            print("Starting a new session. The existing labels file is empty.")
    else:
        master_labels_df = pd.DataFrame(columns=['clip_name', 'event_start_frame', 'event_end_frame', 'severity'])
        print("Starting a new labeling session.")
    
    # --- Filter out already processed clips ---
    labeled_clips = master_labels_df['clip_name'].tolist()
    clips_to_process = predictions_df[~predictions_df['clip_name'].isin(labeled_clips)]
    
    if clips_to_process.empty:
        print("All clips have already been labeled. Nothing to do.")
        return
    
    print(f"\nStarting labeling session. {len(clips_to_process)} clips to process.")
    
    for _, row in clips_to_process.iterrows():
        clip_name = row['clip_name']
        
        print("\n" + "="*80)
        print(f"Processing Clip: {clip_name}")
        print(f"Review the verification frame: {clip_name}_peak.jpg (in your verification_frames folder)")
        print("="*80)
        
        predicted_start = int(row['predicted_start_frame'])
        predicted_end = int(row['predicted_end_frame'])
        print(f"System's Prediction: Start={predicted_start}, End={predicted_end}")
        
        user_input = input("\nAccept this prediction? (y/n/s) [yes, no, skip]: ").lower()
        
        if user_input.startswith('s'): continue
            
        final_start, final_end = predicted_start, predicted_end
        
        if user_input.startswith('n'):
            while True:
                try:
                    final_start = int(input("Enter CORRECT Start Frame: "))
                    final_end = int(input("Enter CORRECT End Frame: "))
                    if final_end >= final_start:
                        break
                    else:
                        print("End frame must be greater than or equal to start frame.")
                except ValueError:
                    print("Invalid input. Please enter numbers.")

        # --- MODIFICATION START: Allow for flexible severity input ---
        severity = ""
        while True:
            user_severity = input("Enter Severity (low/l, medium/m, high/h): ").lower()
            if user_severity in ['low', 'l']:
                severity = 'low'
                break
            elif user_severity in ['medium', 'm']:
                severity = 'medium'
                break
            elif user_severity in ['high', 'h']:
                severity = 'high'
                break
            else:
                print("Invalid input. Please use 'low'/'l', 'medium'/'m', or 'high'/'h'.")
        # --- MODIFICATION END ---

        new_row = pd.DataFrame([{'clip_name': clip_name, 'event_start_frame': final_start, 'event_end_frame': final_end, 'severity': severity}])
        master_labels_df = pd.concat([master_labels_df, new_row], ignore_index=True)
        master_labels_df.to_csv(MASTER_LABELS_OUTPUT_PATH, index=False)
        print(f"✓ Saved label for {clip_name}.")
        
    print("\nLabeling Complete! Master file saved to:", MASTER_LABELS_OUTPUT_PATH)

if __name__ == "__main__":
    main_interactive_labeler()