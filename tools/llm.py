#!/usr/bin/env python3
"""exe.dev LLM gateway client.

The gateway authenticates the VM itself, so no API keys are needed.
Fireworks (GLM-5.2) lives at:
    http://169.254.169.254/gateway/llm/fireworks/inference/v1/chat/completions
Anthropic lives at:
    http://169.254.169.254/gateway/llm/anthropic/v1/messages
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

GATEWAY = os.environ.get("EXEDEV_LLM_GATEWAY", "http://169.254.169.254/gateway/llm")

# Default porter model: GLM-5.2 on Fireworks, via the exe.dev gateway.
PORTER_MODEL = os.environ.get("PORTER_MODEL", "accounts/fireworks/models/glm-5p2")
# Default judge model: a separate agent. Claude Haiku 4.5 is cheap and sharp.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-haiku-4-5")

_THINK_BLOCK = re.compile(r"<(?:thinking|think|reasoning|analysis)>(.*?)</(?:thinking|think|reasoning|analysis)>", re.S)
_FENCE = re.compile(r"^```[a-zA-Z0-9_+\-]*\n", re.M)


def _post(url: str, payload: dict, headers: dict, timeout: int = 1200) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            last = f"HTTP {e.code}: {body[:500]}"
            # transient / rate-limit -> backoff
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except urllib.error.URLError as e:
            last = f"URLError: {e}"
            time.sleep(3 * (attempt + 1))
            continue
    raise RuntimeError(f"gateway request failed after retries: {last}")


def fireworks_chat(model: str, messages: list[dict], *, max_tokens: int = 8000,
                   temperature: float = 0.2, timeout: int = 1800) -> dict:
    """Call a Fireworks chat-completions model through the gateway."""
    url = f"{GATEWAY}/fireworks/inference/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return _post(url, payload, {"content-type": "application/json"}, timeout)


def anthropic_messages(model: str, messages: list[dict], *, max_tokens: int = 4000,
                       system: str | None = None, timeout: int = 600) -> dict:
    """Call an Anthropic messages model through the gateway."""
    url = f"{GATEWAY}/anthropic/v1/messages"
    payload = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        payload["system"] = system
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    return _post(url, payload, headers, timeout)


def strip_reasoning(text: str) -> str:
    """GLM-5.2 habitually emits a visible thinking preamble before its answer.
    Remove <thinking>...</thinking> blocks and obvious numbered analysis prefixes.
    """
    text = _THINK_BLOCK.sub("", text)
    # Drop a leading "1. **Analyze ...**" style preamble up to the first code fence.
    # Heuristic: if the text starts with a numbered analysis step, cut to the first
    # markdown fence or the first blank-line-then-code boundary.
    return text.strip()


def extract_code(text: str) -> str:
    """Pull the contents of the last fenced code block, else return stripped text."""
    fences = re.findall(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", text, re.S)
    if fences:
        return fences[-1][1].strip() + "\n"
    return text.strip() + "\n"


def porter(messages: list[dict], *, max_tokens: int = 8000, temperature: float = 0.2) -> dict:
    """Run the porter agent (GLM-5.2). Returns raw gateway response."""
    return fireworks_chat(PORTER_MODEL, messages, max_tokens=max_tokens, temperature=temperature)


def porter_text(messages: list[dict], *, max_tokens: int = 8000, temperature: float = 0.2) -> tuple[str, dict]:
    """Run porter and return (assistant_text, usage)."""
    resp = porter(messages, max_tokens=max_tokens, temperature=temperature)
    content = resp["choices"][0]["message"]["content"]
    usage = resp.get("usage", {})
    return content, usage


def judge_text(messages: list[dict], *, max_tokens: int = 2000, system: str | None = None) -> tuple[str, dict]:
    """Run the judge agent (Claude Haiku 4.5). Returns (assistant_text, usage)."""
    resp = anthropic_messages(JUDGE_MODEL, messages, max_tokens=max_tokens, system=system)
    content = "".join(b.get("text", "") for b in resp.get("content", []))
    usage = resp.get("usage", {})
    return content, usage


if __name__ == "__main__":
    # tiny smoke test
    if len(sys.argv) > 1 and sys.argv[1] == "porter":
        txt, u = porter_text([{"role": "user", "content": "Say PONG only."}], max_tokens=64)
        print(txt)
        print("usage:", u, file=sys.stderr)
    elif len(sys.argv) > 1 and sys.argv[1] == "judge":
        txt, u = judge_text([{"role": "user", "content": "Reply with exactly: JUDGE-OK"}], max_tokens=64)
        print(txt)
        print("usage:", u, file=sys.stderr)
    else:
        print("usage: llm.py porter|judge", file=sys.stderr)
