"""
download_model.py
-----------------
Ensures the DistilBERT model is downloaded before the ML worker starts.
This keeps the 240MB model out of the Git repository.
"""

import os
import sys
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(SCRIPT_DIR, "..", "onyx-model")
MODEL_FILE = os.path.join(MODEL_DIR, "model.safetensors")

def check_model():
    if os.path.exists(MODEL_FILE):
        size_mb = os.path.getsize(MODEL_FILE) / (1024 * 1024)
        if size_mb > 100:
            print(f"Model already exists ({size_mb:.1f} MB). Skipping download.")
            return True
        else:
            print(f"Warning: model.safetensors is suspiciously small ({size_mb:.1f} MB). Redownloading...")
    return False

def download_model():
    if check_model():
        return

    url = os.environ.get("MODEL_DOWNLOAD_URL")
    if not url:
        print("ERROR: MODEL_DOWNLOAD_URL environment variable is not set!")
        print("Since the onyx-model is not in the Git repository, you MUST provide")
        print("a download URL to a zip file containing the model to run the ML worker.")
        sys.exit(1)

    print(f"Downloading model from {url}...")
    zip_path = os.path.join(SCRIPT_DIR, "..", "onyx-model.zip")
    
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        print(f"ERROR: Failed to download model: {e}")
        sys.exit(1)

    print("Extracting model...")
    os.makedirs(MODEL_DIR, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(MODEL_DIR)
    except Exception as e:
        print(f"ERROR: Failed to extract model zip: {e}")
        sys.exit(1)
        
    # Clean up zip
    try:
        os.remove(zip_path)
    except:
        pass

    if check_model():
        print("Model downloaded and verified successfully.")
    else:
        print("ERROR: Download and extraction finished, but model.safetensors is missing or too small!")
        sys.exit(1)

if __name__ == "__main__":
    download_model()
