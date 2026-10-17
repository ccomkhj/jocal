#!/usr/bin/env python3
"""`jocal summarise`: answers a question about a document of any length with map-reduce on the local model.

    summarise.py <file> <question> --url URL --model ID --notes PATH --max-out N

A PDF goes through `pdftotext -layout` first. The text is split into pages on form feeds, and whole pages are
packed into ~5K-token chunks (chars/4). Each map call sees the question and one chunk and writes notes; one
reduce call answers from the notes alone. The answer goes to stdout, the notes (with the question and the
answer) to PATH, each chunk's as it comes, so they survive a failed call. Talks straight to the runtime's
/v1/messages, allowing each call 900 s; stdlib only. A file with no text exits 2, a failed call 1.
"""

import argparse
import http.client
import json
import subprocess
import sys
import urllib.error
import urllib.request

CHUNK_TOKENS = 5000
CHARS_PER_TOKEN = 4
MAP_MAX_TOKENS = 1000


def text_of(path):
    if path.lower().endswith(".pdf"):
        try:
            return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True,
                                  check=True).stdout
        except FileNotFoundError:
            sys.exit("jocal: pdftotext not found; install poppler (brew install poppler)")
        except subprocess.CalledProcessError as e:
            sys.exit(f"jocal: pdftotext failed on {path}: {e.stderr.strip()}")
    with open(path, errors="replace") as f:
        return f.read()


def pieces(page, limit):
    """A page over the chunk target (a text with no form feeds is one page) is cut on line breaks."""
    if len(page) <= limit:
        return [page]
    out, cur = [], ""
    for line in page.splitlines(keepends=True):
        if cur and len(cur) + len(line) > limit:
            out.append(cur)
            cur = ""
        cur += line
    return out + [cur]


def chunks(text, limit=CHUNK_TOKENS * CHARS_PER_TOKEN):
    """Lists of (page number, text): whole pages packed up to `limit` chars."""
    pages = [(page_no, piece) for page_no, page in enumerate(text.split("\f"), 1) if page.strip()
             for piece in pieces(page, limit)]
    out, cur = [], []
    for page_no, piece in pages:
        if cur and sum(len(text) for _, text in cur) + len(piece) > limit:
            out.append(cur)
            cur = []
        cur.append((page_no, piece))
    return out + [cur] if cur else out


def ask(args, prompt, max_tokens):
    body = json.dumps({"model": args.model, "max_tokens": max_tokens, "temperature": 0.3,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(args.url + "/v1/messages", body, {"Content-Type": "application/json",
                                 "x-api-key": "local", "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"jocal: the runtime refused a request ({e.code}): {e.read().decode(errors='replace')[:500]}")
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:   # refused, reset or timed out
        sys.exit(f"jocal: can't reach the runtime at {args.url} ({getattr(e, 'reason', e)}); notes so far are in {args.notes}")
    return "".join(b.get("text", "") for b in reply["content"] if b.get("type") == "text").strip()


def main():
    ap = argparse.ArgumentParser(prog="jocal summarise")
    ap.add_argument("file")
    ap.add_argument("question")
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--notes", required=True)
    ap.add_argument("--max-out", type=int, required=True)
    args = ap.parse_args()

    parts = chunks(text_of(args.file))
    if not parts:
        print(f"jocal: {args.file} has no text", file=sys.stderr)
        sys.exit(2)
    last_page = parts[-1][-1][0]
    notes = []
    with open(args.notes, "w") as kept:
        def keep(text):
            kept.write(text)
            kept.flush()

        keep(f"# {args.file}\n\nQuestion: {args.question}\n")
        for index, chunk in enumerate(parts, 1):
            first, last = chunk[0][0], chunk[-1][0]
            span = f"pages {first}-{last}" if first != last else f"page {first}"
            print(f"jocal: map {index}/{len(parts)} ({span})", file=sys.stderr)
            text = "\n".join(f"--- page {page_no} ---\n{piece}" for page_no, piece in chunk)
            reply = ask(args, f"Below is {span} of {last_page} of a document.\n\n{text}\n\n"
                              f"Someone will later ask: {args.question}\n"
                              "Write terse bullet-point notes of everything here that would help answer that. "
                              "Keep exact names, numbers and deadlines as written. Do not answer the question yet.",
                        MAP_MAX_TOKENS)
            notes.append(f"## Notes from {span}\n{reply}")
            keep(f"\n{notes[-1]}\n")
        print("jocal: reduce", file=sys.stderr)
        answer = ask(args, "These notes cover every page of a document, in order:\n\n" + "\n\n".join(notes) +
                           f"\n\nUsing only these notes: {args.question}", args.max_out)
        keep(f"\n## Answer\n{answer}\n")
    print(f"jocal: notes kept in {args.notes}", file=sys.stderr)
    print(answer)


if __name__ == "__main__":
    main()
