"""
download_model.py
-----------------
Ensures the DistilBERT model is downloaded before the ML worker starts.
Downloads the production model from the private Hugging Face Hub repository.
"""

import os
import sys

# Deterministic local runtime directory, placed safely in models/downloaded_model
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(SCRIPT_DIR, "downloaded_model")
REPO_ID = "VD-Nagar/onyx-weather-model"

def check_model():
    """Verify if the required model files are present locally."""
    if not os.path.isdir(MODEL_DIR):
        return False

    required_files = [
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json"
    ]

    for f in required_files:
        file_path = os.path.join(MODEL_DIR, f)
        if not os.path.exists(file_path):
            return False

    # Additional size check for model.safetensors
    safetensors_path = os.path.join(MODEL_DIR, "model.safetensors")
    size_mb = os.path.getsize(safetensors_path) / (1024 * 1024)
    if size_mb < 100:
        print(f"Warning: model.safetensors is suspiciously small ({size_mb:.1f} MB). Redownloading...")
        return False

    print(f"Model already exists and verified ({size_mb:.1f} MB). Skipping download.")
    return True

def download_model():
    if check_model():
        return

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable is not set!")
        print(f"You MUST provide a valid Hugging Face token to download the private repository: {REPO_ID}")
        sys.exit(1)

    print(f"Downloading model from Hugging Face Hub: {REPO_ID}...")
    
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub is not installed. Please run 'pip install huggingface_hub'.")
        sys.exit(1)

    try:
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=MODEL_DIR,
            token=hf_token,
            # Only download the necessary inference files, skipping READMEs etc. if desired,
            # but we can just download everything.
            ignore_patterns=["*.md", ".git*"]
        )
    except Exception as e:
        print(f"ERROR: Failed to download model from Hugging Face: {e}")
        sys.exit(1)

    if check_model():
        print("Model downloaded and verified successfully.")
    else:
        print("ERROR: Download finished, but required model files are missing or too small!")
        sys.exit(1)

if __name__ == "__main__":
    download_model()
