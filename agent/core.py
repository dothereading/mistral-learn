"""TutorAgent — the shared agent core."""

import json
import re

from mistralai import Mistral

import config
from agent.memory import (
    list_source_files,
    load_file,
    load_student_profile,
    save_session_log,
)
from agent.prompts import build_system_prompt
from agent.tools import execute_tool, get_available_tools
from db.models import init_database
from db.srs import get_due_reviews


class TutorAgent:
    def __init__(self):
        self.client = Mistral(api_key=config.MISTRAL_API_KEY)
        self.model = config.MISTRAL_MODEL
        self.history: list[dict] = []
        self.profile = load_student_profile()
        self.db = init_database()
        self.soul = load_file("soul/SOUL.md") or ""
        self.skill_index = load_file("skills/index.md") or ""
        self.audio_output: str | None = None
        self.current_mode: str | None = None
        self.on_tool_call: callable | None = None
        self._pending_tool_proposal: dict | None = None

        from custom_tools import load_all

        load_all()

    @property
    def student_level(self) -> str | None:
        """Extract student level from profile if available."""
        if not self.profile:
            return None
        return self.profile.get("level")

    # Common language name -> ISO code mapping (covers common cases;
    # unknown languages fall through as-is so any language works)
    _LANG_CODE_MAP = {
        "spanish": "es", "french": "fr", "german": "de",
        "italian": "it", "portuguese": "pt", "japanese": "ja",
        "chinese": "zh", "mandarin": "zh", "cantonese": "zh",
        "korean": "ko", "arabic": "ar", "russian": "ru",
        "dutch": "nl", "swedish": "sv", "norwegian": "no",
        "danish": "da", "finnish": "fi", "polish": "pl",
        "turkish": "tr", "greek": "el", "hebrew": "he",
        "hindi": "hi", "thai": "th", "vietnamese": "vi",
        "indonesian": "id", "malay": "ms", "tagalog": "tl",
        "swahili": "sw", "czech": "cs", "hungarian": "hu",
        "romanian": "ro", "ukrainian": "uk", "catalan": "ca",
        "persian": "fa", "farsi": "fa", "bengali": "bn",
        "urdu": "ur", "tamil": "ta", "telugu": "te",
    }

    @property
    def target_language(self) -> str | None:
        """Extract target language code from student profile if available."""
        if not self.profile:
            return None
        lang = self.profile.get("language")
        if not lang:
            return None
        first_word = lang.split()[0].lower()
        return self._LANG_CODE_MAP.get(first_word, first_word)

    @property
    def target_language_name(self) -> str | None:
        """Extract full target language name including variant from profile.

        Returns e.g. "Spanish (Spain)", "Portuguese (Brazil)".
        """
        if not self.profile:
            return None
        lang = self.profile.get("language")
        if not lang:
            return None
        variant = self.profile.get("variant")
        return f"{lang} ({variant})" if variant else lang

    def _build_messages(self, user_input: str) -> list[dict]:
        """Build the full messages array with dynamic system prompt."""
        # Reload profile in case tools updated it
        self.profile = load_student_profile()

        due = get_due_reviews(self.db, limit=10)
        sources = list_source_files()

        system = build_system_prompt(
            soul_md=self.soul,
            student_profile=self.profile,
            skill_index=self.skill_index,
            due_reviews=due,
            session_history_summary=self._summarize_if_long(),
            current_mode=self.current_mode,
            available_sources=sources if sources else None,
        )

        trimmed = self._trim_history(max_turns=20)

        return [
            {"role": "system", "content": system},
            *trimmed,
            {"role": "user", "content": user_input},
        ]

    def chat(self, user_input: str) -> str:
        """Main chat method. Returns assistant response text."""
        self.audio_output = None

        self._detect_mode_switch(user_input)
        messages = self._build_messages(user_input)

        max_iterations = 10  # Safety limit on tool call loops
        for _ in range(max_iterations):
            response = self.client.chat.complete(
                model=self.model,
                messages=messages,
                tools=get_available_tools(),
                tool_choice="auto",
            )

            msg = response.choices[0].message

            # No tool calls — we have our final response
            if not msg.tool_calls:
                reply = msg.content or ""

                # Guard: if the model returned a bare tool name instead of a
                # real response (Mistral quirk after parallel tool calls),
                # nudge it to actually generate the text.
                tool_names = {
                    t["function"]["name"]
                    for t in get_available_tools()
                }
                if reply.strip() in tool_names:
                    messages.append({"role": "assistant", "content": reply})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[System: You returned a tool name instead of a "
                            "response. Please generate your actual reply now.]"
                        ),
                    })
                    continue

                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": reply})

                # Log session
                save_session_log(f"**User**: {user_input}\n\n**Tutor**: {reply}\n")

                return reply

            # Validate tool calls — filter out malformed ones
            valid_tool_calls = []
            for tc in msg.tool_calls:
                if re.fullmatch(r"[a-zA-Z0-9_\-.]{1,256}", tc.function.name):
                    valid_tool_calls.append(tc)
                elif self.on_tool_call:
                    self.on_tool_call("__malformed__", tc.function.name[:80])

            if not valid_tool_calls:
                # All tool calls were malformed; ask the model to retry
                # Include text from the malformed attempt so context isn't lost
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "[System: Your tool call failed because the function name "
                        "was invalid. Remember: call tools by name like "
                        "add_source, read_source, read_skill, search_youtube, "
                        "lookup_wikipedia. Arguments go in the arguments object, "
                        "NOT in the function name. Try again.]"
                    ),
                })
                continue

            # Process valid tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in valid_tool_calls
                ],
            })

            for tc in valid_tool_calls:
                if self.on_tool_call:
                    self.on_tool_call(tc.function.name, tc.function.arguments)
                result = execute_tool(tc.function.name, tc.function.arguments, self)
                messages.append({
                    "role": "tool",
                    "name": tc.function.name,
                    "content": str(result),
                    "tool_call_id": tc.id,
                })

        # If we exhaust iterations, return whatever we have
        return msg.content or "I seem to be having trouble. Could you try again?"

    def _detect_mode_switch(self, user_input: str) -> None:
        """Simple keyword detection for mode changes."""
        lower = user_input.lower()
        mode_keywords = {
            "review": "Knowledge Review",
            "quiz me": "Knowledge Review",
            "content": "Content-Based Learning",
            "read": "Content-Based Learning",
            "listen": "Content-Based Learning",
            "roleplay": "Role Play",
            "role play": "Role Play",
            "practice conversation": "Role Play",
            "question": "Q&A",
            "q&a": "Q&A",
            "how do you say": "Q&A",
        }
        for keyword, mode in mode_keywords.items():
            if keyword in lower:
                self.current_mode = mode
                return

    def _trim_history(self, max_turns: int = 20) -> list[dict]:
        """Keep last N user/assistant message pairs."""
        if len(self.history) <= max_turns * 2:
            return list(self.history)
        return self.history[-(max_turns * 2):]

    def _summarize_if_long(self) -> str | None:
        """If history is long, summarize the trimmed portion."""
        if len(self.history) <= 40:
            return None
        # Summarize the older messages that were trimmed
        trimmed = self.history[:-(20 * 2)]
        topics = set()
        for msg in trimmed:
            if msg["role"] == "user":
                topics.add(msg["content"][:80])
        if topics:
            return "Earlier in this session, the student discussed: " + "; ".join(list(topics)[:5])
        return None
