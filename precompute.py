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
    if with_ai:
        import llm
        if llm.FAILED:
            print(f"{len(llm.FAILED)} Gemini call(s) failed ({llm.FAILED[0]}), so {out} was NOT written: a snapshot built "
                  "while Gemini was down would have no AI readings in it. Try again in a few minutes; the answers that "
                  "did arrive are cached, so only the failed ones are asked again.")
            return 1
    snapshot.save(out, data_dir, results, ai=with_ai)
    if with_ai:
        used = sorted(e for e, r in results.items() if r.get("ai_assisted") or r.get("ai_consulted"))
        print(f"wrote {out}: {len(results)} emails in the file, Gemini was used on only {len(used)} of them "
              f"({', '.join(used) or 'none'}); the other {len(results) - len(used)} are unchanged")
    else:
        print(f"wrote {out} for {len(results)} emails")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
