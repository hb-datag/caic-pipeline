"""The ONE gateway for every LLM call in the pipeline.

Design rule (from the project brief): all model calls go through
`generate(prompt, schema)`. Swapping backends — open-weights vLLM on Modal,
Gemini free tier, or the Claude API — is a config change in
pipeline/config.py (or the CAIC_LLM_BACKEND env var), never a code change.

Guardrails for smaller open models:
  * every output is parsed as JSON and validated against a JSON schema
  * on failure, ONE retry with the validation error appended to the prompt
"""

import json
import os
import re

import jsonschema
import requests

from . import config


class LLMError(RuntimeError):
    """Raised when the backend fails or output never validates."""


DEFAULT_SYSTEM = (
    "You are a precise analysis engine. Respond with ONLY a single valid JSON "
    "object matching the requested structure. No prose, no markdown fences."
)


def generate(prompt: str, schema: dict, *, system: str = DEFAULT_SYSTEM,
             max_tokens: int = 4096) -> dict:
    """Run one LLM call and return schema-valid JSON (retrying once)."""
    attempt_prompt = prompt
    last_err = None
    for attempt in (1, 2):
        raw = _call_backend(attempt_prompt, system, max_tokens)
        try:
            data = _extract_json(raw)
            jsonschema.validate(data, schema)
            return data
        except (ValueError, jsonschema.ValidationError) as err:
            last_err = err
            attempt_prompt = (
                f"{prompt}\n\nYour previous reply was invalid: {err}.\n"
                "Reply again with ONLY a single valid JSON object matching the schema."
            )
    raise LLMError(f"Output failed validation after retry: {last_err}")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _call_backend(prompt: str, system: str, max_tokens: int) -> str:
    backend = config.LLM_BACKEND
    if backend == "vllm":
        return _call_vllm(prompt, system, max_tokens)
    if backend == "gemini":
        return _call_gemini(prompt, system, max_tokens)
    if backend == "anthropic":
        return _call_anthropic(prompt, system, max_tokens)
    raise LLMError(f"Unknown LLM_BACKEND: {backend!r}")


def ensure_ready(log=print, timeout_s: int = 120) -> None:
    """Verify the model server is reachable (no-op for API backends).

    Polls the OpenAI-standard /v1/models endpoint (served by Ollama, vLLM,
    and LM Studio alike). The CAIC server is an always-on workstation, so a
    couple of minutes of retries covers a reboot; past that we surface the
    operator contact message from config.OFFLINE_MESSAGE."""
    if config.LLM_BACKEND != "vllm":
        return
    if not config.VLLM_BASE_URL:
        raise LLMError("CAIC_VLLM_BASE_URL is not set. " + config.OFFLINE_MESSAGE)
    import time
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            if requests.get(f"{config.VLLM_BASE_URL}/v1/models",
                            headers=_vllm_headers(), timeout=15).status_code == 200:
                return
        except requests.RequestException:
            pass
        log("model server not answering yet — retrying…")
        time.sleep(15)
    raise LLMError("The AI model server is not reachable. " + config.OFFLINE_MESSAGE)


def _vllm_headers() -> dict:
    # The server reuses CAIC_PASSCODE as its API key (see modal_app.vllm_server).
    return {"Authorization": f"Bearer {os.environ.get('CAIC_PASSCODE', '')}"}


def _call_vllm(prompt: str, system: str, max_tokens: int) -> str:
    """Any OpenAI-compatible server (Ollama on the CAIC 5090, vLLM, LM Studio)."""
    if not config.VLLM_BASE_URL:
        raise LLMError("CAIC_VLLM_BASE_URL is not set. " + config.OFFLINE_MESSAGE)
    try:
        resp = requests.post(
            f"{config.VLLM_BASE_URL}/v1/chat/completions",
            headers=_vllm_headers(),
            json={
                "model": config.VLLM_MODEL,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=600,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise LLMError(f"Model server request failed ({exc.__class__.__name__}). "
                       + config.OFFLINE_MESSAGE) from exc
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, system: str, max_tokens: int) -> str:
    """Google Gemini free tier — needs GEMINI_API_KEY in a Modal secret."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set (add it to a Modal secret)")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent")
    resp = requests.post(
        url,
        headers={"x-goog-api-key": key},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_anthropic(prompt: str, system: str, max_tokens: int) -> str:
    """Claude API (paid) — needs ANTHROPIC_API_KEY in a Modal secret."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY not set (add it to a Modal secret)")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": config.ANTHROPIC_MODEL,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


# ---------------------------------------------------------------------------
# Output cleanup — small models love markdown fences and stray prose
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Pull the outermost JSON object out of a model reply."""
    # Qwen-class models may emit <think>…</think> reasoning first — drop it.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start:end + 1])
