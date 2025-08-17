import asyncio
import openai
import json
import re
from typing import Dict, List, Optional
from models.schemas import TopicIdea, ScriptPackage
from nlp.prompts import IDEA_TO_OUTLINE_PROMPT, OUTLINE_TO_SCRIPT_PROMPT, METADATA_PROMPT
from nlp.safety import SafetyChecker
from loguru import logger
import os
from dotenv import load_dotenv

load_dotenv()

class ScriptWriter:
    def __init__(self, api_key: Optional[str] = None):
        self.client = openai.AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.safety_checker = SafetyChecker()

    async def create_script_package(
        self, 
        idea: TopicIdea, 
        niche: str, 
        banned_terms: List[str]
    ) -> Optional[ScriptPackage]:
        """Create complete script package from topic idea"""
        try:
            # Step 1: Idea → Outline
            outline_result = await self._idea_to_outline(idea, niche)
            if not outline_result:
                return None

            # Step 2: Select best hook and create script
            best_hook = outline_result['hooks'][0]  # Use first hook
            script_text = await self._outline_to_script(outline_result, best_hook)
            if not script_text:
                return None

            # Step 3: Generate metadata
            metadata = await self._generate_metadata(idea, script_text, niche)
            if not metadata:
                return None

            # Step 4: Safety check
            is_safe = await self.safety_checker.check_content(
                metadata['title'], script_text, niche, banned_terms
            )
            if not is_safe:
                logger.warning(f"Content failed safety check for idea {idea.id}")
                return None

            # Create script package
            package = ScriptPackage(
                topic_id=idea.id,
                hook=best_hook,
                script_text=script_text,
                word_count=len(script_text.split()),
                title=metadata['title'],
                description=metadata['description'],
                hashtags=metadata['hashtags']
            )

            logger.info(f"Created script package for {idea.id}: {package.title}")
            return package

        except Exception as e:
            logger.error(f"Error creating script package for {idea.id}: {e}")
            return None

    async def _idea_to_outline(self, idea: TopicIdea, niche: str) -> Optional[Dict]:
        """Convert topic idea to outline with hooks"""
        try:
            prompt = IDEA_TO_OUTLINE_PROMPT.format(
                niche=niche,
                seed_title=idea.title
            )

            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional short-form video producer. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.8
            )

            result = response.choices[0].message.content
            
            # Parse JSON response
            outline_data = json.loads(result)
            
            # Validate structure
            required_keys = ['hooks', 'outline', 'keywords']
            if all(key in outline_data for key in required_keys):
                return outline_data
            else:
                logger.error(f"Invalid outline structure: {outline_data}")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in outline response: {e}")
            return None
        except Exception as e:
            logger.error(f"Error generating outline: {e}")
            return None

    async def _outline_to_script(self, outline_data: Dict, hook: str) -> Optional[str]:
        """Convert outline to full script with strict length control (80–120)."""
        try:
            prompt = OUTLINE_TO_SCRIPT_PROMPT.format(
                outline=outline_data['outline'],
                hook=hook
            )

            # First attempt
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional scriptwriter for short-form vertical videos. Write engaging, fast-paced content."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=220,
                temperature=0.6
            )
            script = response.choices[0].message.content.strip()
            wc = len(script.split())
            if 80 <= wc <= 120:
                return script

            # Retry once with explicit constraint
            retry_prompt = (
                prompt
                + f"\n\nRewrite STRICTLY to {80}-{120} words. Current length: {wc}. "
                  "Short sentences, no fluff. Keep the same message."
            )
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a precise script compressor/expander. Obey word count strictly."},
                    {"role": "user", "content": retry_prompt}
                ],
                max_tokens=220,
                temperature=0.4
            )
            script = response.choices[0].message.content.strip()
            wc = len(script.split())
            if 80 <= wc <= 120:
                return script

            # Last-resort: pad/trim to bounds (so pipeline doesn't die)
            if wc < 80:
                filler = " Quick recap with key points." * ((80 - wc + 6) // 7)
                script = (script + filler).strip()
            elif wc > 120:
                script = " ".join(script.split()[:120])
            return script

        except Exception as e:
            logger.error(f"Error generating script: {e}")
            return None

    async def _generate_metadata(self, idea: TopicIdea, script: str, niche: str) -> Optional[Dict]:
        """Generate title, description, and hashtags with robust JSON handling."""
        try:
            script_preview = script[:100] + "..." if len(script) > 100 else script

            prompt = METADATA_PROMPT.format(
                title=idea.title,
                script_preview=script_preview,
                niche=niche
            )

            # Try JSON mode first
            try:
                resp = await self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a YouTube optimization expert. Return STRICT JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=280,
                    temperature=0.5,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content
                metadata = json.loads(raw)
            except Exception as e:
                logger.warning(f"JSON mode failed, falling back: {e}")
                # Fallback: normal completion, then extract {...}
                resp = await self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a YouTube optimization expert. Return STRICT JSON only."},
                        {"role": "user", "content": prompt + "\nReturn ONLY JSON in this exact shape: {\"title\":\"...\",\"description\":\"...\",\"hashtags\":[\"#...\"]}"}
                    ],
                    max_tokens=280,
                    temperature=0.4,
                )
                s = resp.choices[0].message.content.strip()
                i, j = s.find("{"), s.rfind("}")
                if i == -1 or j == -1 or j <= i:
                    raise ValueError("No JSON object found in metadata response.")
                cleaned = re.sub(r",\s*([}\]])", r"\1", s[i:j+1])
                metadata = json.loads(cleaned)

            # Validate structure
            if not isinstance(metadata, dict) or \
               "title" not in metadata or "description" not in metadata or "hashtags" not in metadata:
                raise ValueError("Metadata missing required keys.")

            if len(metadata.get("title", "")) > 65:
                metadata["title"] = metadata["title"][:65].rstrip()

            # Ensure hashtags are valid
            tags = metadata.get("hashtags") or []
            if not isinstance(tags, list):
                tags = []
            if "#shorts" not in [t.lower() for t in tags]:
                tags.insert(0, "#shorts")
            tags = [t if t.startswith("#") else f"#{t}" for t in tags]
            if len(tags) < 7:
                tags += ["#news", "#tech", "#ai", "#explained", "#learn", "#today"]
            metadata["hashtags"] = tags[:12]

            return metadata

        except Exception as e:
            logger.error(f"Invalid JSON in metadata response: {e}")
            # Fallback metadata so pipeline continues
            return {
                "title": idea.title[:60] or "Quick Breakdown",
                "description": "Highlights and key takeaways.\nSubscribe for more.",
                "hashtags": ["#shorts", "#news", "#tech", "#ai", "#explained", "#today", "#learn"]
            }

    async def retry_with_different_hook(
        self, 
        idea: TopicIdea, 
        niche: str, 
        banned_terms: List[str],
        attempt: int = 1
    ) -> Optional[ScriptPackage]:
        """Retry script generation with different parameters."""
        if attempt > 3:
            return None

        logger.info(f"Retry attempt {attempt} for idea {idea.id}")

        outline_result = await self._idea_to_outline(idea, niche)
        if not outline_result or len(outline_result['hooks']) <= attempt:
            return None

        hook_index = min(attempt, len(outline_result['hooks']) - 1)
        selected_hook = outline_result['hooks'][hook_index]

        script_text = await self._outline_to_script(outline_result, selected_hook)
        if not script_text:
            return await self.retry_with_different_hook(idea, niche, banned_terms, attempt + 1)

        metadata = await self._generate_metadata(idea, script_text, niche)
        if not metadata:
            return await self.retry_with_different_hook(idea, niche, banned_terms, attempt + 1)

        is_safe = await self.safety_checker.check_content(
            metadata['title'], script_text, niche, banned_terms
        )
        if not is_safe:
            return await self.retry_with_different_hook(idea, niche, banned_terms, attempt + 1)

        return ScriptPackage(
            topic_id=idea.id,
            hook=selected_hook,
            script_text=script_text,
            word_count=len(script_text.split()),
            title=metadata['title'],
            description=metadata['description'],
            hashtags=metadata['hashtags']
        )