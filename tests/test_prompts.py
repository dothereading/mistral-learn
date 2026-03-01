"""Tests for agent/prompts.py — dynamic system prompt builder."""

from agent.prompts import (
    build_system_prompt,
    content_learning_write_prompt,
    content_learning_short_answer_prompt,
    knowledge_review_prompt,
    roleplay_prompt,
    qa_prompt,
    custom_prompt,
    _get_mode_instructions,
)


class TestBuildSystemPrompt:
    def test_new_user_prompt(self):
        prompt = build_system_prompt(
            soul_md="# Soul\nBe a tutor.",
            student_profile=None,
            skill_index="- spanish: Spanish knowledge",
            due_reviews=[],
        )
        assert "# Soul" in prompt
        assert "New Student" in prompt
        assert "onboarding" in prompt.lower()
        assert "spanish" in prompt

    def test_returning_user_prompt(self):
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="- Level: A2\n- Target language: Spanish",
            skill_index="- spanish: test",
            due_reviews=[],
        )
        assert "Current Student" in prompt
        assert "Level: A2" in prompt
        assert "Session Start" in prompt

    def test_with_current_mode(self):
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="- Level: A2",
            skill_index="",
            due_reviews=[],
            current_mode="Knowledge Review",
        )
        assert "Current Mode: Knowledge Review" in prompt
        assert "Session Start" not in prompt

    def test_with_due_reviews(self):
        reviews = [
            {
                "item_type": "vocab",
                "word": "hola",
                "translation": "hello",
                "last_reviewed": "2026-02-28",
            },
            {
                "item_type": "grammar",
                "pattern_name": "ser vs estar",
                "pattern_description": "permanent vs temporary",
                "last_reviewed": "never",
            },
        ]
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile=None,
            skill_index="",
            due_reviews=reviews,
        )
        assert "Items Due for Review (2 total)" in prompt
        assert "hola" in prompt
        assert "ser vs estar" in prompt

    def test_with_available_sources(self):
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="test",
            skill_index="",
            due_reviews=[],
            available_sources=["cooking-article.txt", "soccer-news.txt"],
        )
        assert "Available Source Material" in prompt
        assert "cooking-article.txt" in prompt
        assert "soccer-news.txt" in prompt

    def test_no_sources_section_when_empty(self):
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="test",
            skill_index="",
            due_reviews=[],
            available_sources=None,
        )
        assert "Source Material" not in prompt

    def test_session_history_summary(self):
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="test",
            skill_index="",
            due_reviews=[],
            session_history_summary="Student practiced food vocabulary and ser vs estar.",
        )
        assert "This Session So Far" in prompt
        assert "food vocabulary" in prompt

    def test_all_sections_present(self):
        """Full prompt with all sections should include all parts."""
        prompt = build_system_prompt(
            soul_md="# Soul Content",
            student_profile="- Level: B1",
            skill_index="- teaching-methods: scaffolding",
            due_reviews=[{"item_type": "vocab", "word": "gato", "translation": "cat", "last_reviewed": "never"}],
            current_mode="Content-Based Learning",
            available_sources=["article.txt"],
            session_history_summary="Discussed animals.",
        )
        assert "# Soul Content" in prompt
        assert "Current Student" in prompt
        assert "Current Mode: Content-Based Learning" in prompt
        assert "gato" in prompt
        assert "article.txt" in prompt
        assert "teaching-methods" in prompt
        assert "Discussed animals" in prompt

    def test_mode_instructions_injected_not_old_reference(self):
        """build_system_prompt should inject actual mode instructions, not 'See Session Modes'."""
        prompt = build_system_prompt(
            soul_md="# Soul",
            student_profile="- Level: A2",
            skill_index="",
            due_reviews=[],
            current_mode="Knowledge Review",
        )
        assert "See Session Modes" not in prompt
        assert "SRS" in prompt


class TestModePromptBuilders:
    def test_content_learning_write_prompt_story(self):
        result = content_learning_write_prompt("about 4 paragraphs", None, None)
        assert "Content-Based Learning" in result
        assert "about 4 paragraphs" in result
        assert "WRITING RULES" in result

    def test_content_learning_write_prompt_search(self):
        result = content_learning_write_prompt("about 1 paragraph", "search", "cooking")
        assert "search_youtube" in result
        assert "lookup_wikipedia" in result
        assert "cooking" in result

    def test_content_learning_write_prompt_url(self):
        result = content_learning_write_prompt("about 10 paragraphs", "url", "https://example.com")
        assert "add_source" in result
        assert "read_source" in result
        assert "https://example.com" in result

    def test_content_learning_short_answer_prompt(self):
        result = content_learning_short_answer_prompt()
        assert "short-answer" in result or "short answer" in result.lower()
        assert "summarize" in result

    def test_knowledge_review_prompt(self):
        result = knowledge_review_prompt()
        assert "SRS" in result or "due" in result
        assert "flashcard" in result.lower() or "natural" in result.lower()

    def test_roleplay_prompt(self):
        result = roleplay_prompt()
        assert "character" in result or "waiter" in result
        assert "recasting" in result.lower()

    def test_qa_prompt(self):
        result = qa_prompt()
        assert "grammar" in result or "cultural" in result

    def test_custom_prompt(self):
        result = custom_prompt()
        assert "Student directs" in result

    def test_get_mode_instructions_known(self):
        result = _get_mode_instructions("Role Play")
        assert "recasting" in result.lower()

    def test_get_mode_instructions_unknown(self):
        result = _get_mode_instructions("Nonexistent Mode")
        assert result == ""
