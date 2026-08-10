# citadel/commands/ai.py
"""Ask-the-AI command: sends a question to a locally-running Ollama
model and replies privately to the asker. Runs entirely on-device --
no external API, no network dependency, matching this project's
resilient/infrastructure-free design.

Replies are deliberately kept short (system prompt + a token cap):
LoRa's small packet size and multi-second inter-packet delay make a
normal-length chatbot response impractical, not the model's latency.
"""

import asyncio
import logging

import requests

from citadel.commands.base import BaseCommand, CommandCategory
from citadel.commands.registry import register_command
from citadel.auth.permissions import PermissionLevel
from citadel.transport.packets import ToUser

log = logging.getLogger(__name__)

MAX_REPLY_CHARS = 400


@register_command
class AskAICommand(BaseCommand):
    code = "A"
    name = "ask_ai"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Ask the AI"
    help_text = "Ask the local AI a question. Usage: A <question>"

    async def run(self, context):
        question = (self.args or "").strip()
        if not question:
            return ToUser(
                session_id=context.session_id,
                text="Usage: A <question>",
                is_error=True,
                error_code="missing_question"
            )

        ai_config = context.config.ai
        if not ai_config.get("enabled", False):
            return ToUser(
                session_id=context.session_id,
                text="AI is currently disabled.",
                is_error=True,
                error_code="ai_disabled"
            )

        try:
            reply = await self._ask_ollama(ai_config, question)
        except requests.exceptions.ConnectionError:
            log.error("AskAICommand: could not connect to Ollama")
            return ToUser(
                session_id=context.session_id,
                text="AI is unavailable right now. Try again later.",
                is_error=True,
                error_code="ai_unavailable"
            )
        except requests.exceptions.Timeout:
            log.error("AskAICommand: Ollama request timed out")
            return ToUser(
                session_id=context.session_id,
                text="AI took too long to respond. Try a shorter question.",
                is_error=True,
                error_code="ai_timeout"
            )
        except Exception as err:
            log.exception(f"AskAICommand: unexpected error: {err}")
            return ToUser(
                session_id=context.session_id,
                text="AI error. Please try again.",
                is_error=True,
                error_code="ai_error"
            )

        return ToUser(session_id=context.session_id, text=reply)

    async def _ask_ollama(self, ai_config, question: str) -> str:
        """Blocking HTTP call to Ollama, wrapped in asyncio.to_thread --
        same idiom used for paho-mqtt calls in mqtt_publisher.py, the
        codebase's one established pattern for a synchronous call inside
        async code."""
        system_prompt = ai_config.get("system_prompt", "")
        prompt = f"{system_prompt}\n\n{question}" if system_prompt else question

        response = await asyncio.to_thread(
            requests.post,
            ai_config.get("ollama_url", "http://localhost:11434/api/generate"),
            json={
                "model": ai_config.get("model", "llama3.2:3b"),
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": ai_config.get("max_tokens", 200)},
            },
            timeout=ai_config.get("timeout", 60),
        )
        response.raise_for_status()
        data = response.json()
        reply = data.get("response", "").strip()
        if not reply:
            raise ValueError("Ollama returned an empty response")

        # Defensive truncation in case the model ignores the length
        # instruction in the system prompt.
        if len(reply) > MAX_REPLY_CHARS:
            reply = reply[:MAX_REPLY_CHARS - 1].rstrip() + "…"

        return reply
