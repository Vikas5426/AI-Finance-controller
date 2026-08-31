import os
import sys
import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

api_key = os.getenv("GEMINI_API_KEY")
print("=" * 60)
print("  API KEY DIAGNOSTIC & CONNECTIVITY CHECK")
print("=" * 60)
print(f"Key configured: {'Yes' if api_key else 'No'}")
if api_key:
    masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
    print(f"Key preview: {masked} (length: {len(api_key)})")

# Test 1: Direct HTTP call to Google Generative Language REST API
print("\n--- Test 1: Direct REST API (generativelanguage.googleapis.com) ---")
try:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    resp = requests.get(url, timeout=10)
    print(f"HTTP Status Code: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        models = [m.get("name") for m in data.get("models", [])[:5]]
        print("[SUCCESS] API Key is VALID and ACTIVE!")
        print(f"Available sample models: {models}")
    else:
        print(f"[FAILED] HTTP {resp.status_code}")
        print(f"Response body: {resp.text}")
except Exception as e:
    print(f"[ERROR] during REST request: {e}")

# Test 2: google.genai SDK
print("\n--- Test 2: google.genai SDK Content Generation ---")
try:
    from google import genai
    client = genai.Client(api_key=api_key)
    # Test generation on gemini-3.6-flash and gemini-3.6-pro
    for model_name in ["gemini-3.6-flash", "gemini-3.6-pro"]:
        try:
            print(f"Attempting generate_content with model '{model_name}'...")
            res = client.models.generate_content(
                model=model_name,
                contents="Hello AI Financial Controller! Reply with 'CONFIRMED: Gemini API is fully operational and generating responses.'"
            )
            print(f"[SUCCESS] Response received from {model_name}:")
            print(f">>> {res.text.strip()}")
            break
        except Exception as e:
            print(f"  Model {model_name} attempt error: {e}")
except Exception as e:
    print(f"[ERROR] google.genai initialization error: {e}")

print("\n" + "=" * 60)


