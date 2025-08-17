# nlp/safety.py

import os
from typing import List, Tuple, Dict, Any
from loguru import logger
from openai import AsyncOpenAI

class SafetyChecker:
    """
    Allows channel-specific tolerance for 'tone-only' issues while blocking real policy risks.
    Configure via:
      SAFETY_PROFILE=strict|lenient|edgy   (default: edgy)
      DRY_RUN_TOLERANT=true|false          (default: true)
    """
    TONE_PATTERNS = (
        "negative sentiment",
        "sarcastic",
        "snark",
        "derogatory",
        "offensive",
        "harsh tone",
        "provocative",
        "aggressive",
        "mocking",
        "hostile",
    )

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
        self.profile = os.getenv("SAFETY_PROFILE", "edgy").lower()
        self.dry_run_tolerant = os.getenv("DRY_RUN_TOLERANT", "true").lower() == "true"
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def _llm_safety_check(self, title: str, script: str, niche: str, banned_terms: List[str]) -> Dict[str, Any]:
        from nlp.prompts import SAFETY_CHECK_PROMPT
        prompt = SAFETY_CHECK_PROMPT.format(
            title=title, script=script, niche=niche, banned_terms=banned_terms
        )
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict policy reviewer. Return ONLY JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            data = resp.choices[0].message.content
        except Exception:
            # Fallback: best-effort without forced JSON
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict policy reviewer. Return ONLY JSON."},
                    {"role": "user", "content": prompt + "\nReturn JSON: {\"safe\":true/false,\"issues\":[\"...\"],\"severity\":\"low/medium/high\"}"}
                ],
                temperature=0,
            )
            data = resp.choices[0].message.content

        import json, re
        try:
            i, j = data.find("{"), data.rfind("}")
            data = data if i == -1 else data[i:j+1]
            data = re.sub(r",\s*([}\]])", r"\1", data)
            parsed = json.loads(data)
        except Exception:
            parsed = {"safe": False, "issues": ["Safety reviewer returned invalid JSON"], "severity": "medium"}
        return parsed

    def _contains(self, patterns: Tuple[str, ...], text: str) -> bool:
        t = text.lower()
        return any(p in t for p in patterns)

    def _is_soft_tone_only(self, issues: List[str], severity: str) -> bool:
        """True if all issues are tone/sentiment and NONE are hard policy risks."""
        if severity.lower() == "high":
            return False
        if not issues:
            return False
        # if ANY hard risk shows up, it's not soft tone-only
        if any(self._contains(self.HARD_RISK_PATTERNS, i) for i in issues):
            return False
        # require that ALL issues look like tone/sentiment flags
        return all(self._contains(self.TONE_PATTERNS, i) for i in issues)

    async def check_content(self, title: str, script: str, niche: str, banned_terms: List[str]) -> bool:
        # Quick local banned terms scan (hard block)
        text = f"{title}\n{script}".lower()
        for term in (banned_terms or []):
            if term and term.lower() in text:
                logger.warning(f"Safety: blocked by banned term: '{term}'")
                return False

        result = await self._llm_safety_check(title, script, niche, banned_terms)
        safe = bool(result.get("safe", False))
        issues = result.get("issues", []) or []
        severity = str(result.get("severity", "medium"))

        if safe:
            return True

        # Tone-only tolerance
        if self._is_soft_tone_only(issues, severity):
            if self.profile in ("edgy", "lenient"):
                logger.warning(f"Safety: tone-only issues allowed (profile={self.profile}): {issues}")
                return True
            # In strict mode, optionally allow during dry-run
            if self.profile == "strict" and self.dry_run_tolerant:
                logger.warning(f"Safety: tone-only issues allowed for dry-run (strict+dry_run_tolerant): {issues}")
                return True

        # Otherwise, block
        logger.warning(f"Safety: blocked. Severity: {severity}, Issues: {issues}")
        return False
