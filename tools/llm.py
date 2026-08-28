"""
LLM integration via local vLLM (Qwen3.6-27B) using OpenAI-compatible API.
Uses distilled skill instructions (Purpose + Process only) for fast context windows.
"""

import asyncio
import re
import time
from pydantic import SecretStr
from tools.distiller import distill_skill
from tools.context_manager import prepare_context_for_llm
from tools.prompt_logger import log_llm_call

_import_error = None
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError as e:
    _import_error = str(e)
    ChatOpenAI = None  # type: ignore[assignment,misc]
    HumanMessage = None  # type: ignore[assignment,misc]
    SystemMessage = None  # type: ignore[assignment,misc]

from config.loader import config  # noqa: E402

# ── Prompt injection protection ──────────────────────────────────────
_USER_INPUT_MARKER_START = "<<USER_INPUT_START>>"
_USER_INPUT_MARKER_END = "<<USER_INPUT_END>>"
_PROMPT_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+all\s+instructions|system\s*:?|<\s*system|</\s*system|"
    r"disregard\s+previous|ignore\s+previous|you\s+are\s+now|"
    r"despite\s+what|act\s+as\s+if|pretend\s+to|roleplay|"
    r"^\s*\[\/?root\]|\[system:|execute\.system|eval\()",
    re.IGNORECASE,
)


def _sanitize_user_input(text: str) -> str:
    """Wrap user-provided text in delimiters and filter injection attempts.

    This wraps content so the model can distinguish instructions from user data,
    and flags suspicious patterns for the model to reject.
    """
    if not text:
        return text
    # Flag injection patterns by prefixing with a warning
    flagged = _PROMPT_INJECTION_PATTERNS.sub(
        lambda m: f"[WARNING: INJECTION_ATTEMPT: {m.group(0)}]", text
    )
    return f"{_USER_INPUT_MARKER_START}\n{flagged}\n{_USER_INPUT_MARKER_END}"


# ── LLM failure contract (Decision 3) ────────────────────────────────
# Fatal LLM failures (timeout, 429/5xx after bounded retry, provider
# errors) raise LLMError after backoff is exhausted. invoke_skill /
# invoke_skill_async catch it, log, and return None so the owning phase
# fails cleanly instead of treating an error string as valid content.


class LLMError(Exception):
    """Fatal LLM failure that has exhausted its bounded retry budget."""

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        retryable: bool = True,
        attempt: int = 0,
    ):
        super().__init__(message)
        self.cause = cause
        self.retryable = retryable
        self.attempt = attempt


# Bounded exponential backoff (seconds) with a small deterministic jitter.
_RETRY_BACKOFF_BASE = 1.0
_RETRY_BACKOFF_CAP = 15.0
_DEFAULT_MAX_RETRIES = 2  # i.e. up to 3 attempts total
_LLM_TIMEOUT_S = 180.0


def _backoff_sleep(attempt: int, seed: str = "") -> None:
    """Sleep base * 2**attempt (capped), plus a small seed-derived jitter."""
    delay = min(_RETRY_BACKOFF_BASE * (2**attempt), _RETRY_BACKOFF_CAP)
    jitter = (sum(ord(c) for c in seed) % 7) / 10.0
    time.sleep(delay + jitter)


def _is_retryable(exc: BaseException) -> bool:
    """Classify an LLM call exception as retryable (transient) or fatal."""
    # Transient HTTP/timeout conditions are retryable; hard provider
    # failures (auth, model-not-found) are not.
    text = f"{type(exc).__name__} {exc}".lower()
    fatal_markers = (
        "401",
        "403",
        "unauthorized",
        "authentication",
        "invalid api key",
        "api key not valid",
        "404",
        "model not found",
        "does not exist",
        "invalid_request",
        "context_length_exceeded",
        "llmtimeout",
    )
    if any(m in text for m in fatal_markers):
        return False
    # httpx / openai transient errors, connection/timeout errors, 408/429/5xx
    return True


class _LLMTimeout(Exception):
    """Raised when a blocking LLM invoke exceeds its wall-clock budget."""


def _invoke_with_timeout(llm, messages, timeout_s: float):
    """Run a blocking llm.invoke in a worker thread bounded by *timeout_s*.

    The call runs in a daemon thread so that even if it hangs the timeout
    still fires and the caller is unblocked. The underlying SDK call cannot
    be hard-cancelled mid-flight, but the orchestrator is no longer blocked
    waiting on it, and the hung thread will die when the worker exits or
    when the model connection is torn down.
    """
    import threading

    result: list = []
    error: list = []
    done = threading.Event()

    def _run():
        try:
            result.append(llm.invoke(messages))
        except Exception as e:  # noqa: PERF203 - re-raised by the joiner
            error.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if not done.wait(timeout=timeout_s):
        raise _LLMTimeout(f"LLM invoke exceeded {timeout_s}s")
    if error:
        raise error[0]
    return result[0]


def _invoke_with_retry(
    llm,
    messages,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    timeout_s: float = _LLM_TIMEOUT_S,
    seed: str = "",
):
    """Invoke *llm* with a per-call timeout and bounded backoff.

    Returns the LLM response on success. Raises LLMError when every attempt
    fails. Transient errors retry; fatal errors raise immediately.
    """
    attempts = max(0, max_retries) + 1
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            # Best-effort wall-clock timeout: bound a blocking call whether it
            # runs on the calling thread or in a worker thread (async callers
            # go through asyncio.to_thread). Raises on expiry.
            return _invoke_with_timeout(llm, messages, timeout_s)
        except Exception as e:  # noqa: PERF203 - per-call classification
            last_exc = e
            if attempt + 1 >= attempts or not _is_retryable(e):
                break
            logger = None
            try:
                from log.logging import log_event, setup_logger

                logger = setup_logger("llm")
                log_event(
                    logger,
                    "llm.retry",
                    attempt=attempt + 1,
                    error=str(e),
                )
            except Exception:
                pass
            _backoff_sleep(attempt, seed=seed)
    raise LLMError(
        f"LLM call failed after {attempts} attempt(s): {last_exc}",
        cause=last_exc,
        retryable=_is_retryable(last_exc) if last_exc else False,
        attempt=attempts,
    )


def get_llm(model: str | None = None, base_url: str | None = None):
    """Get a configured LLM instance. Returns None if langchain_openai unavailable."""
    from config.loader import config as _cfg

    if ChatOpenAI is None:
        print(
            f"WARNING: langchain_openai not installed ({_import_error}). Running in dry-run mode."
        )
        return None

    if not model:
        model = config.services.llm.model
    if not base_url:
        base_url = _cfg.services.llm.base_url

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=SecretStr(config.services.llm.api_key),
        temperature=config.services.llm.temperature,
        max_tokens=config.services.llm.max_tokens,  # type: ignore[call-arg]
    )


def invoke_skill(
    skill_content: str,
    task: str,
    context: str = "",
    llm=None,
    max_prompt_chars: int = 2000,
    workflow_id: str = "",
    phase: str = "",
):
    """
    Invoke a skill: distill instructions, manage context size, log prompts,
    send to LLM, and return the response.
    """
    from service.otel_instrumentor import tracer
    from service import health as health_module
    from log.logging import log_event, setup_logger

    logger = setup_logger("llm")
    skill_name = task[:80] if task else "unknown"
    start = time.time()

    if llm is None:
        llm = get_llm()

    model = config.services.llm.model
    max_tokens = config.services.llm.max_tokens

    if llm is None:
        result = f"[DRY-RUN] Skill({len(skill_content)} chars) → Task: {task}"
        log_event(
            logger,
            "llm.dry_run",
            skill=skill_name,
            workflow_id=workflow_id,
            phase=phase,
        )
        return result

    # ── Context management ──
    contexts = {
        "skill_instructions": distill_skill(skill_content, max_chars=max_prompt_chars),
        "task": f"Task: {task}",
        "context": context,
    }
    prepared = prepare_context_for_llm(contexts, max_tokens=max_tokens)
    headroom_info = prepared["headroom"]

    # Use compressed context from prepare_context_for_llm — not raw contexts
    compressed_context = _sanitize_user_input(prepared["context"])

    system_prompt = (
        f"You are an expert following these instructions:\n\n"
        f"{contexts['skill_instructions']}\n\n"
        f"Respond with actionable output. Be specific, include file paths, "
        f"code snippets, and verification steps."
    )
    user_prompt = (
        _sanitize_user_input(compressed_context)
        if compressed_context
        else _sanitize_user_input(contexts["task"])
    )

    try:
        response = _invoke_with_retry(
            llm,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ],
            seed=skill_name,
        )
        response_text = str(response.content)
        duration = time.time() - start

        # ── Log prompt/response ──
        log_llm_call(
            workflow_id=workflow_id,
            phase=phase,
            skill=skill_name,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response_text,
            duration_s=duration,
        )

        # ── Trace LLM call ──
        tracer.record_llm_call(
            skill=skill_name,
            model=model,
            prompt_len=len(system_prompt) + len(user_prompt),
            response_len=len(response_text),
            duration_s=duration,
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=True)
        log_event(
            logger,
            "llm.success",
            skill=skill_name,
            model=model,
            duration_s=round(duration, 3),
            prompt_len=len(system_prompt),
            response_len=len(response_text),
            context_tokens=prepared["total_tokens"],
            headroom_pct=headroom_info["headroom_pct"],
        )
        return response_text

    except Exception as e:
        duration = time.time() - start

        # ── Log error ──
        log_llm_call(
            workflow_id=workflow_id,
            phase=phase,
            skill=skill_name,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response="",
            duration_s=duration,
            error=str(e),
        )

        tracer.record_llm_call(
            skill=skill_name,
            model=model,
            prompt_len=0,
            response_len=0,
            duration_s=duration,
            error=str(e),
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=False)
        log_event(logger, "llm.error", skill=skill_name, error=str(e))
        return None


async def invoke_skill_async(
    skill_content: str,
    task: str,
    context: str = "",
    llm=None,
    max_prompt_chars: int = 2000,
    workflow_id: str = "",
    phase: str = "",
):
    """Async version of invoke_skill — runs the blocking LLM call in a thread pool so multiple
    independent skill invocations can run concurrently via asyncio.gather()."""
    from service.otel_instrumentor import tracer
    from service import health as health_module
    from log.logging import log_event, setup_logger

    logger = setup_logger("llm")
    skill_name = task[:80] if task else "unknown"
    start = time.time()

    if llm is None:
        llm = get_llm()

    model = config.services.llm.model
    max_tokens = config.services.llm.max_tokens

    if llm is None:
        result = f"[DRY-RUN] Skill({len(skill_content)} chars) → Task: {task}"
        log_event(
            logger,
            "llm.dry_run",
            skill=skill_name,
            workflow_id=workflow_id,
            phase=phase,
        )
        return result

    # ── Context management ──
    contexts = {
        "skill_instructions": distill_skill(skill_content, max_chars=max_prompt_chars),
        "task": f"Task: {task}",
        "context": context,
    }
    prepared = prepare_context_for_llm(contexts, max_tokens=max_tokens)
    headroom_info = prepared["headroom"]

    compressed_context = prepared["context"]

    system_prompt = (
        f"You are an expert following these instructions:\n\n"
        f"{contexts['skill_instructions']}\n\n"
        f"Respond with actionable output. Be specific, include file paths, "
        f"code snippets, and verification steps."
    )
    user_prompt = compressed_context if compressed_context else contexts["task"]

    def _invoke():
        response = _invoke_with_retry(
            llm,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ],
            seed=skill_name,
        )
        return str(response.content)

    try:
        response_text = await asyncio.to_thread(_invoke)
        duration = time.time() - start

        log_llm_call(
            workflow_id=workflow_id,
            phase=phase,
            skill=skill_name,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response_text,
            duration_s=duration,
        )
        tracer.record_llm_call(
            skill=skill_name,
            model=model,
            prompt_len=len(system_prompt) + len(user_prompt),
            response_len=len(response_text),
            duration_s=duration,
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=True)
        log_event(
            logger,
            "llm.success",
            skill=skill_name,
            model=model,
            duration_s=round(duration, 3),
            prompt_len=len(system_prompt),
            response_len=len(response_text),
            context_tokens=prepared["total_tokens"],
            headroom_pct=headroom_info["headroom_pct"],
        )
        return response_text

    except Exception as e:
        duration = time.time() - start
        log_llm_call(
            workflow_id=workflow_id,
            phase=phase,
            skill=skill_name,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response="",
            duration_s=duration,
            error=str(e),
        )
        tracer.record_llm_call(
            skill=skill_name,
            model=model,
            prompt_len=0,
            response_len=0,
            duration_s=duration,
            error=str(e),
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=False)
        log_event(logger, "llm.error", skill=skill_name, error=str(e))
        return None
