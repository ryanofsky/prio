"""OpenRouter backend: the same prompts sent to other models for comparison.

Any model name starting with ``openrouter/`` is routed here instead of the
Anthropic SDK, e.g. ``openrouter/deepseek/deepseek-chat-v3-0324``. The
OpenAI-style chat API is used over plain HTTP (no extra dependency), with
the JSON schema passed as ``response_format`` where the model supports it.
No batching, no prompt caching, no thinking controls; requests run with a
small thread pool. OpenRouter reports the dollar cost of each request in
``usage.cost`` when asked, which is stored as cost_usd.

The key is read from OPENROUTER_API_KEY or ~/.config/prio/openrouter-key.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

URL = "https://openrouter.ai/api/v1/chat/completions"
PREFIX = "openrouter/"


def is_openrouter(model: str) -> bool:
    return model.startswith(PREFIX)


def _key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        p = Path.home() / ".config" / "prio" / "openrouter-key"
        if p.exists():
            k = p.read_text().strip()
    if not k:
        raise RuntimeError("no OpenRouter key: set OPENROUTER_API_KEY or create ~/.config/prio/openrouter-key")
    return k


def chat(model: str, system: list[dict] | str, user: str, schema: dict | None, max_tokens: int, retries: int = 3):
    """One chat completion. Returns an object shaped like the Anthropic SDK's
    message as far as the pipeline reads it: .content[0].text, .stop_reason,
    .usage (input_tokens, output_tokens, cost)."""
    sys_text = system if isinstance(system, str) else "\n\n".join(b["text"] for b in system)
    body = {
        "model": model[len(PREFIX):],
        "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ryanofsky/prio", "X-Title": "prio",
    })
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                out = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(last)
    choice = (out.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    # Some models wrap JSON in a code fence despite response_format.
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
        text = t.strip()
    finish = choice.get("finish_reason")
    u = out.get("usage") or {}
    usage = SimpleNamespace(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0),
                            cache_creation_input_tokens=0, cache_read_input_tokens=0, cost=u.get("cost"))
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           stop_reason="end_turn" if finish in ("stop", None) else finish, usage=usage,
                           model=out.get("model"), provider=(out.get("provider") or ""))


def run_many(jobs: list, fn, workers: int | None = None):
    """Run fn(job) over jobs with a thread pool, yielding results as they
    complete (not in order), so progress is visible; exceptions are yielded
    in place. Workers default to $PRIO_OPENROUTER_WORKERS or 4."""
    from concurrent.futures import as_completed
    workers = workers or int(os.environ.get("PRIO_OPENROUTER_WORKERS", "4"))
    def safe(j):
        try:
            return fn(j)
        except Exception as e:  # keep going; the caller records the failure
            return e
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(safe, j) for j in jobs]
        for f in as_completed(futures):
            yield f.result()
