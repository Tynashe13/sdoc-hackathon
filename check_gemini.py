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


# python check_gemini.py --models : which models can this key use right now, and which of them are busy?
if "--models" in os.sys.argv:
    try:
        client = genai.Client(api_key=key)
        names = sorted(m.name.replace("models/", "") for m in client.models.list()
                       if "generateContent" in (getattr(m, "supported_actions", None) or []))
        flash = [n for n in names if "flash" in n and "preview" not in n and "image" not in n and "tts" not in n]
        print("\nModels that can write text with this key (flash family):", ", ".join(flash) or "none found")
        for name in [model] + [n for n in flash if n != model][:6]:
            try:
                client.models.generate_content(model=name, contents="Reply with the single word: OK")
                print(f"  {name}: works right now")
            except Exception as exc:
                print(f"  {name}: FAILED ({getattr(exc, 'code', None)}) {str(exc)[:90]}")
        print("\nTo change the fallback list: GEMINI_FALLBACK_MODELS=name1,name2 in .env")
    except Exception as exc:
        print("Could not list models ->", type(exc).__name__, str(exc)[:300])
