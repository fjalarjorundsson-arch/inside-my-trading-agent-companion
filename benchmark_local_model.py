"""Measure one repeatable local-model job (Chapter 13).

Sends the same synthetic evidence package to an OpenAI-compatible local server
(LM Studio by default) several times and records, per request:

  - total elapsed seconds and time to first token (streaming)
  - prompt and completion tokens, as reported by the server when available
  - generation throughput (completion tokens / generation seconds)
  - whether the answer is valid JSON with an allowed verdict and only
    evidence IDs that exist in the package

Standard library only. Nothing leaves localhost.

    python benchmark_local_model.py --model qwen/qwen3.6-27b --runs 10
    python benchmark_local_model.py --base-url http://127.0.0.1:1234/v1 --out results.csv

Peak VRAM and power are NOT measured here. Read them while the benchmark runs
(LM Studio's resource view, AMD Software / Task Manager, a wall power meter)
and write them into the notes column of the sheet by hand.
"""
import argparse
import csv
import json
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

VERDICTS = {"confirm", "weaken", "veto", "insufficient"}

PACKAGE = {
    "schema_version": "book_demo_v1",
    "note": "SYNTHETIC teaching package - invented company and values",
    "subject": {"symbol": "DEMO", "name": "Demo Industries (fictional)"},
    "base_hypothesis": {"direction": "positive", "source": "deterministic score"},
    "evidence": [
        {"id": "price_summary_01", "kind": "price",
         "text": "Last completed close 103.0; 20-session return +4.1%; "
                 "20-session volatility 1.8% daily; no gaps in the series."},
        {"id": "news_01", "kind": "news",
         "text": "Headline: Demo Industries says demand 'remains strong' "
                 "ahead of results. No figures given."},
        {"id": "calendar_01", "kind": "calendar",
         "text": "Next earnings: estimated date in 9 days, session unknown."},
    ],
    "missing": ["current_financial_release"],
}

SYSTEM_PROMPT = (
    "You review one supplied evidence package. Use only facts in the package. "
    "Judge the base hypothesis as confirm, weaken, veto or insufficient. "
    "Cite only evidence ids that appear in the package. "
    "Return only a JSON object with keys verdict, evidence_ids, missing, reason."
)


def check_answer(text):
    """Return (valid, reason) for a model answer against the teaching contract."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return False, "not_json"
    if not isinstance(value, dict):
        return False, "not_object"
    if value.get("verdict") not in VERDICTS:
        return False, "bad_verdict"
    known = {item["id"] for item in PACKAGE["evidence"]}
    cited = value.get("evidence_ids")
    if not isinstance(cited, list) or not cited:
        return False, "no_evidence_ids"
    if any(item not in known for item in cited):
        return False, "invented_evidence_id"
    return True, ""


def strip_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    # Some reasoning models emit a think block first.
    if "</think>" in text:
        text = text.split("</think>", 1)[-1]
    return text.strip()


def one_request(base_url, model, max_tokens, timeout):
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(PACKAGE, sort_keys=True)},
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first_token = None
    parts, usage = [], {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    if first_token is None:
                        first_token = time.perf_counter()
                    parts.append(piece)
    ended = time.perf_counter()
    text = "".join(parts)
    total = ended - started
    ttft = (first_token - started) if first_token else None
    completion = usage.get("completion_tokens")
    generation_seconds = (ended - first_token) if first_token else None
    tps = (completion / generation_seconds
           if completion and generation_seconds and generation_seconds > 0 else None)
    valid, reason = check_answer(strip_fences(text))
    return {
        "total_s": round(total, 3),
        "ttft_s": round(ttft, 3) if ttft is not None else "",
        "prompt_tokens": usage.get("prompt_tokens", ""),
        "completion_tokens": completion if completion is not None else "",
        "gen_tokens_per_s": round(tps, 2) if tps else "",
        "valid": valid,
        "failure": reason,
    }


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", default="qwen/qwen3.6-27b")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--out", default="benchmark_results.csv")
    parser.add_argument("--label", default="", help="free text, e.g. 'Q4_K_M ctx8192'")
    args = parser.parse_args(argv)

    host = args.base_url.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
    if host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("this benchmark only talks to a local server")

    rows = []
    fields = ["run", "kind", "started_utc", "model", "label", "total_s", "ttft_s",
              "prompt_tokens", "completion_tokens", "gen_tokens_per_s",
              "valid", "failure", "notes"]
    print(f"Warm-up request to {args.model} (not counted)...")
    for run in range(args.runs + 1):
        kind = "warmup" if run == 0 else "measured"
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            result = one_request(args.base_url, args.model, args.max_tokens, args.timeout)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result = {"total_s": "", "ttft_s": "", "prompt_tokens": "",
                      "completion_tokens": "", "gen_tokens_per_s": "",
                      "valid": False, "failure": f"request_error: {exc}"[:120]}
        row = {"run": run, "kind": kind, "started_utc": stamp, "model": args.model,
               "label": args.label, "notes": "", **result}
        rows.append(row)
        print(f"  {kind:8} #{run:<2} total={row['total_s']}s ttft={row['ttft_s']}s "
              f"tok/s={row['gen_tokens_per_s']} valid={row['valid']} {row['failure']}")

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    measured = [r for r in rows if r["kind"] == "measured"]
    totals = [r["total_s"] for r in measured if r["total_s"] != ""]
    speeds = [r["gen_tokens_per_s"] for r in measured if r["gen_tokens_per_s"] != ""]
    ttfts = [r["ttft_s"] for r in measured if r["ttft_s"] != ""]
    print()
    print(f"Machine: {platform.platform()} | Python {platform.python_version()}")
    print(f"Measured runs: {len(measured)}, valid answers: "
          f"{sum(1 for r in measured if r['valid'])}")
    if totals:
        print(f"Total time  median {statistics.median(totals):.2f}s, "
              f"p90 {percentile(totals, 0.9):.2f}s")
    if ttfts:
        print(f"First token median {statistics.median(ttfts):.2f}s")
    if speeds:
        print(f"Generation  median {statistics.median(speeds):.1f} tokens/s")
    print(f"Results written to {args.out}. Add peak VRAM and power by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
