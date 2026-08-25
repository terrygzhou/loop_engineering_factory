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
    r'(ignore\s+all\s+instructions|system\s*:?|<\s*system|</\s*system|'
    r'disregard\s+previous|ignore\s+previous|you\s+are\s+now|'
    r'despite\s+what|act\s+as\s+if|pretend\s+to|roleplay|'
    r'^\s*\[\/?root\]|\[system:|execute\.system|eval\()',
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
    flagged = _PROMPT_INJECTION_PATTERNS.sub(lambda m: f"[WARNING: INJECTION_ATTEMPT: {m.group(0)}]", text)
    return f"{_USER_INPUT_MARKER_START}\n{flagged}\n{_USER_INPUT_MARKER_END}"


def get_llm(model: str | None = None, base_url: str | None = None):
    """Get a configured LLM instance. Returns None if langchain_openai unavailable."""
    from config.loader import config as _cfg
    if ChatOpenAI is None:
        print(f"WARNING: langchain_openai not installed ({_import_error}). Running in dry-run mode.")
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

def invoke_skill(skill_content: str, task: str, context: str = "", llm=None, max_prompt_chars: int = 2000,
                  workflow_id: str = "", phase: str = ""):
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
        log_event(logger, "llm.dry_run", skill=skill_name, workflow_id=workflow_id, phase=phase)
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
    compressed_context = _sanitize_user_input(prepared['context'])

    system_prompt = (
        f"You are an expert following these instructions:\n\n"
        f"{contexts['skill_instructions']}\n\n"
        f"Respond with actionable output. Be specific, include file paths, "
        f"code snippets, and verification steps."
    )
    user_prompt = _sanitize_user_input(compressed_context) if compressed_context else _sanitize_user_input(contexts['task'])

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
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
        log_event(logger, "llm.success", skill=skill_name, model=model, duration_s=round(duration, 3),
                  prompt_len=len(system_prompt), response_len=len(response_text),
                  context_tokens=prepared["total_tokens"], headroom_pct=headroom_info["headroom_pct"])
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
        return f"[LLM ERROR] {e}"


async def invoke_skill_async(skill_content: str, task: str, context: str = "", llm=None, max_prompt_chars: int = 2000,
                             workflow_id: str = "", phase: str = ""):
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
        log_event(logger, "llm.dry_run", skill=skill_name, workflow_id=workflow_id, phase=phase)
        return result

    # ── Context management ──
    contexts = {
        "skill_instructions": distill_skill(skill_content, max_chars=max_prompt_chars),
        "task": f"Task: {task}",
        "context": context,
    }
    prepared = prepare_context_for_llm(contexts, max_tokens=max_tokens)
    headroom_info = prepared["headroom"]

    compressed_context = prepared['context']

    system_prompt = (
        f"You are an expert following these instructions:\n\n"
        f"{contexts['skill_instructions']}\n\n"
        f"Respond with actionable output. Be specific, include file paths, "
        f"code snippets, and verification steps."
    )
    user_prompt = compressed_context if compressed_context else contexts['task']

    def _invoke():
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        return str(response.content)

    try:
        response_text = await asyncio.to_thread(_invoke)
        duration = time.time() - start

        log_llm_call(
            workflow_id=workflow_id, phase=phase, skill=skill_name, model=model,
            system_prompt=system_prompt, user_prompt=user_prompt,
            response=response_text, duration_s=duration,
        )
        tracer.record_llm_call(
            skill=skill_name, model=model,
            prompt_len=len(system_prompt) + len(user_prompt),
            response_len=len(response_text), duration_s=duration,
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=True)
        log_event(logger, "llm.success", skill=skill_name, model=model, duration_s=round(duration, 3),
                  prompt_len=len(system_prompt), response_len=len(response_text),
                  context_tokens=prepared["total_tokens"], headroom_pct=headroom_info["headroom_pct"])
        return response_text

    except Exception as e:
        duration = time.time() - start
        log_llm_call(
            workflow_id=workflow_id, phase=phase, skill=skill_name, model=model,
            system_prompt=system_prompt, user_prompt=user_prompt,
            response="", duration_s=duration, error=str(e),
        )
        tracer.record_llm_call(
            skill=skill_name, model=model,
            prompt_len=0, response_len=0, duration_s=duration, error=str(e),
        )
        health_module.track_llm(skill=skill_name, duration=duration, success=False)
        log_event(logger, "llm.error", skill=skill_name, error=str(e))
        return f"[LLM ERROR] {e}"
