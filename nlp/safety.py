# nlp/safety.py

import os
from typing import List, Tuple, Dict, Any
from loguru import logger

# Optional import kept for compatibility with existing environments
# (We won't actually call the API; this prevents import errors if elsewhere referenced)
try:
    from openai import AsyncOpenAI  # noqa: F401
except Exception:
    AsyncOpenAI = None  # type: ignore


class SafetyChecker:
    """
    NO-OP SafetyChecker

    This implementation preserves the same class, constructor, and method
    signatures as your previous SafetyChecker, and you can keep calling it
    exactly the same way in your pipeline. However, it performs no real
    safety checks and never blocks.

    - No banned-term scanning
    - No LLM calls
    - Always returns True from check_content()

    Environment variables are read (to keep behavior surface identical) but
    have no effect on the outcome.
    """

    # Kept for compatibility; not used in logic
    TONE_PATTERNS = (
        "negative sentiment",
        "sarcastic",
        "snark",
        "derogatory",
        "offensive",
        "harsh tone",
        "provocative",
        "aggressive",
        "medical advice",
        "health advice",
        "treatment",
        "cure",
        "diagnosis",
        "prescription",
        "health insurer",
        "medical claim",
        "doctor says",
        "health tip",
        "mocking",
        "hostile",
    )

    # Kept for compatibility; not used in logic
    HARD_RISK_PATTERNS = (
        "medical",
        "financial advice",
        "guaranteed returns",
        "misleading information",
        "copyright",
        "hate",
        "slur",
        "violence",
        "illegal",
        "privacy",
        "doxx",
        "harassment",
        "self-harm",
        "dangerous",
        "terror",
        "exploit",
        "adult",
    )

    def __init__(self):
        # Read the same env vars to avoid surprising missing-variable errors elsewhere
        self.profile = os.getenv("SAFETY_PROFILE", "edgy").lower()
        self.dry_run_tolerant = os.getenv("DRY_RUN_TOLERANT", "true").lower() == "true"
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key_present = bool(os.getenv("OPENAI_API_KEY"))

        # We deliberately do not instantiate an OpenAI client or make any calls.
        # The presence/absence of the key is logged only for transparency.
        if self.api_key_present:
            logger.debug("SafetyChecker (NO-OP): OPENAI_API_KEY detected but will not be used.")
        else:
            logger.debug("SafetyChecker (NO-OP): No OPENAI_API_KEY found (not needed).")

    # --- Compatibility helpers (unused in NO-OP) -----------------------------

    async def _llm_safety_check(
        self, title: str, script: str, niche: str, banned_terms: List[str]
    ) -> Dict[str, Any]:
        """
        Preserved for API compatibility. Returns a 'safe' result without calling any LLM.
        """
        logger.debug("SafetyChecker (NO-OP): _llm_safety_check called; returning safe=True without evaluation.")
        return {"safe": True, "issues": [], "severity": "low"}

    def _contains(self, patterns: Tuple[str, ...], text: str) -> bool:
        # Preserved for API compatibility; not used.
        return False

    def _is_soft_tone_only(self, issues: List[str], severity: str) -> bool:
        # Preserved for API compatibility; not used.
        return True

    # --- Public API ----------------------------------------------------------

    async def check_content(
        self, title: str, script: str, niche: str, banned_terms: List[str]
    ) -> bool:
        """
        NO-OP: Always returns True.

        Parameters are accepted and logged so the call sites remain unchanged,
        but no checks are performed and nothing is ever blocked.
        """
        logger.info(
            "SafetyChecker (NO-OP): check_content called "
            f"(profile={self.profile}, dry_run_tolerant={self.dry_run_tolerant}, model={self.model}). "
            "No safety checks will be performed; returning True."
        )
        logger.debug(
            "SafetyChecker (NO-OP): Context snapshot — "
            f"title='{(title or '')[:80]}', niche='{niche}', "
            f"banned_terms_count={len(banned_terms or [])}, script_len={len(script or '')}"
        )

        # Do not scan banned terms; do not call LLM; always permit.
        return True
