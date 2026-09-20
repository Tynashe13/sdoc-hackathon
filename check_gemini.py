"""Quick check that your Gemini key + model work.  Run:  python check_gemini.py
Makes ONE small call and prints either the answer or the exact error."""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
print("key found:", bool(key), "| key length:", len(key or ""), "| model:", model)
try:
    client = genai.Client(api_key=key)
    reply = client.models.generate_content(model=model, contents="Reply with the single word: OK")
    print("SUCCESS ->", reply.text)
except Exception as exc:
    print("FAILED ->", type(exc).__name__, "| code:", getattr(exc, "code", None))
    print(str(exc)[:600])
