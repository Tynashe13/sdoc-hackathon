"""Write results.json so the web app starts instantly.

    python precompute.py [data_dir]     rules only, so the file is reproducible
    python precompute.py --with-ai      also let Gemini read scans (needs GEMINI_API_KEY)
    python precompute.py --check        exit 1 if results.json is missing or out of date

Run it again after changing the data or any of the checking code, then commit results.json.
"""
import os
import sys


def main(argv):
    with_ai, check = "--with-ai" in argv, "--check" in argv
    args = [a for a in argv if not a.startswith("--")]
    data_dir = args[0] if args else os.getenv("DATA_DIR", "data")
    out = os.getenv("RESULTS_FILE", "results.json")
    if not with_ai:
        os.environ["USE_LLM"] = "0"          # must be set before llm is imported
    import snapshot
    if check:
        fresh = snapshot.load(out, data_dir) is not None
        print(f"{out} is up to date" if fresh else
              f"{out} is missing or does not match this checkout. If you changed the data or the checking "
              "code, run python precompute.py. If you did not, a data file may be damaged: restore data/ from Git.")
        return 0 if fresh else 1
    import pipeline
    results = pipeline.run(data_dir)
    snapshot.save(out, data_dir, results, ai=with_ai)
    print(f"wrote {out} for {len(results)} emails")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
