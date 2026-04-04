"""Tests for Claude Code state detection from terminal output."""

from __future__ import annotations

import time

from hort.extensions.core.code_watch.detect import ClaudeState, detect_state


# ── Idle states ───────────────────────────────────────────────────


class TestIdleDetection:
    def test_empty_prompt_is_idle(self) -> None:
        output = "❯\xa0\n──────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n\n"
        s = detect_state(output)
        assert s.state == "idle"

    def test_prompt_with_text_is_idle(self) -> None:
        output = "❯ hello world\n──────\n  ⏵⏵ bypass permissions on\n\n"
        s = detect_state(output)
        assert s.state == "idle"

    def test_empty_output_is_idle(self) -> None:
        s = detect_state("")
        assert s.state == "idle"

    def test_only_blanks_is_idle(self) -> None:
        s = detect_state("\n\n\n\n")
        assert s.state == "idle"


# ── Mode detection ────────────────────────────────────────────────


class TestModeDetection:
    def test_dangerous_mode(self) -> None:
        output = "❯\xa0\n──────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
        s = detect_state(output)
        assert s.mode == "dangerous"

    def test_plan_mode(self) -> None:
        output = "❯\xa0\n──────\n  ⏸ plan mode on (shift+tab to cycle)\n"
        s = detect_state(output)
        assert s.mode == "plan"

    def test_accept_edits_mode(self) -> None:
        output = "❯\xa0\n──────\n  ⏵⏵ accept edits on (shift+tab to cycle)\n"
        s = detect_state(output)
        assert s.mode == "accept_edits"

    def test_normal_mode_no_indicator(self) -> None:
        output = "❯\xa0\n──────\n  ? for shortcuts\n"
        s = detect_state(output)
        assert s.mode == "normal"


# ── Thinking / working states ─────────────────────────────────────


class TestThinkingDetection:
    def test_harmonizing(self) -> None:
        output = "❯ write a story\n\n✻ Harmonizing...\n\n  ⏵⏵ bypass permissions on · esc to interrupt\n"
        s = detect_state(output)
        assert s.state == "thinking"

    def test_waddling(self) -> None:
        output = "❯\xa0please write something\n\n✻ Waddling...\n\n  ⏵⏵ bypass permissions on · esc to interrupt\n"
        s = detect_state(output)
        assert s.state == "thinking"

    def test_random_verb(self) -> None:
        output = "❯ do stuff\n\n✻ Stewing...\n\n  ⏵⏵ bypass permissions on · esc to interrupt\n"
        s = detect_state(output)
        assert s.state == "thinking"

    def test_esc_to_interrupt_overrides_prompt(self) -> None:
        """Even if ❯ prompt is visible, 'esc to interrupt' means working."""
        output = (
            "❯\xa0please write me a story\n"
            "──────\n"
            "✻ Undulating...\n"
            "❯\xa0\n"
            "──────\n"
            "  ⏵⏵ bypass permissions on · esc to interrupt\n"
        )
        s = detect_state(output)
        assert s.state == "thinking"
        assert s.mode == "dangerous"

    def test_no_esc_to_interrupt_means_idle(self) -> None:
        """Without 'esc to interrupt', ❯ prompt = idle."""
        output = "❯\xa0\n──────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
        s = detect_state(output)
        assert s.state == "idle"


# ── Response streaming ────────────────────────────────────────────


class TestRespondingDetection:
    def test_response_streaming(self) -> None:
        output = "❯ hi\n\n⏺ Hello! How can I help you today?\n\n  ⏵⏵ bypass permissions on\n"
        s = detect_state(output)
        assert s.state == "responding"

    def test_long_response(self) -> None:
        output = (
            "❯ write a story\n\n"
            "⏺ Once upon a time, in a small cottage...\n\n"
            "  But clever Hansel had a plan.\n\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        s = detect_state(output)
        # The last meaningful line is story text, not ⏺ — could be busy
        # but the ⏺ should be detected in recent lines
        assert s.state in ("responding", "busy")


# ── Tool execution ────────────────────────────────────────────────


class TestToolDetection:
    def test_tool_running(self) -> None:
        output = "! ls\n  ⎿ CLAUDE.md\n     frontend\n\n  ⏵⏵ bypass permissions on\n"
        s = detect_state(output)
        assert s.state == "tool_running"

    def test_tool_with_output(self) -> None:
        output = (
            "! cat README.md\n"
            "  ⎿ # My Project\n"
            "     Some description\n"
            "     … +20 lines\n\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        s = detect_state(output)
        assert s.state == "tool_running"


# ── Selection (numbered list) ─────────────────────────────────────


class TestSelectionDetection:
    def test_numbered_selection(self) -> None:
        output = (
            "  Which approach?\n\n"
            "  1. Option A — do this\n"
            "  2. Option B — do that\n"
            "  3. Option C — something else\n\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        s = detect_state(output)
        assert s.state == "selecting"

    def test_numbered_with_cursor(self) -> None:
        output = (
            "  1. Fix the bug\n"
            "  2. Add tests\n"
            "  3. Refactor\n\n"
            "  ⏸ plan mode on\n"
        )
        s = detect_state(output)
        assert s.state == "selecting"
        assert s.mode == "plan"


# ── State continuity (since tracking) ─────────────────────────────


class TestSinceContinuity:
    def test_same_state_preserves_since(self) -> None:
        output1 = "❯\xa0\n──────\n  ⏵⏵ bypass permissions on\n"
        s1 = detect_state(output1, session_name="test")

        # Same state → since preserved
        s2 = detect_state(output1, session_name="test", previous_state=s1)
        assert s2.since == s1.since

    def test_different_state_resets_since(self) -> None:
        output_idle = "❯\xa0\n──────\n  ⏵⏵ bypass permissions on\n"
        output_thinking = "✻ Harmonizing...\n\n  ⏵⏵ bypass permissions on\n"

        s1 = detect_state(output_idle, session_name="test")
        old_since = s1.since

        import time
        time.sleep(0.01)

        s2 = detect_state(output_thinking, session_name="test", previous_state=s1)
        assert s2.since > old_since
        assert s2.state == "thinking"

    def test_idle_seconds(self) -> None:
        s = ClaudeState(state="idle", since=time.time() - 10)
        assert 9 < s.idle_seconds < 11

    def test_non_idle_zero_seconds(self) -> None:
        s = ClaudeState(state="thinking", since=time.time() - 10)
        assert s.idle_seconds == 0


# ── Properties ────────────────────────────────────────────────────


class TestProperties:
    def test_is_idle(self) -> None:
        assert ClaudeState(state="idle").is_idle
        assert not ClaudeState(state="thinking").is_idle

    def test_is_working(self) -> None:
        assert ClaudeState(state="thinking").is_working
        assert ClaudeState(state="tool_running").is_working
        assert ClaudeState(state="responding").is_working
        assert not ClaudeState(state="idle").is_working

    def test_needs_input(self) -> None:
        assert ClaudeState(state="idle").needs_input
        assert ClaudeState(state="selecting").needs_input
        assert ClaudeState(state="permission").needs_input
        assert not ClaudeState(state="thinking").needs_input


# ── Real-world output samples ─────────────────────────────────────


class TestRealWorldSamples:
    def test_full_idle_screen(self) -> None:
        """Real output from an idle Claude Code session."""
        output = (
            " ▐▛███▜▌   Claude Code v2.1.91\n"
            "▝▜█████▛▘  Opus 4.6 (1M context) with high effort · Claude Max\n"
            "  ▘▘ ▝▝    ~/projects/llming-plumber\n"
            "\n"
            "❯ hi\n"
            "\n"
            "⏺ Hi! How can I help you today?\n"
            "\n"
            "──────────────────────────────────────\n"
            "❯\xa0\n"
            "──────────────────────────────────────\n"
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
            "\n\n\n"
        )
        s = detect_state(output)
        assert s.state == "idle"
        assert s.mode == "dangerous"

    def test_plan_mode_idle(self) -> None:
        output = (
            "──────────────────────────────────────\n"
            "❯\xa0\n"
            "──────────────────────────────────────\n"
            "  ⏸ plan mode on (shift+tab to cycle)\n"
            "\n"
        )
        s = detect_state(output)
        assert s.state == "idle"
        assert s.mode == "plan"

    def test_mid_response(self) -> None:
        output = (
            "❯ tell me about python\n"
            "\n"
            "⏺ Python is a high-level programming language known for its\n"
            "  readability and versatility. Created by Guido van Rossum\n"
            "\n"
            "  ⏵⏵ bypass permissions on\n"
        )
        s = detect_state(output)
        assert s.state in ("responding", "busy")

    def test_thinking_with_harmonizing(self) -> None:
        output = (
            "❯ just write me a short story\n"
            "\n"
            "✻ Harmonizing...\n"
            "\n"
            "  ⏵⏵ bypass permissions on · esc to interrupt\n"
        )
        s = detect_state(output)
        assert s.state == "thinking"
        assert s.mode == "dangerous"

    def test_working_with_prompt_visible(self) -> None:
        """Real scenario: prompt + Waddling + esc to interrupt."""
        output = (
            "! pwd\n"
            "  ⎿ /Users/michael/projects/llming-plumber\n"
            "\n"
            "❯\xa0please write me a single html file bakery site in html\n"
            "\n"
            "✻ Waddling...\n"
            "\n"
            "❯\xa0\n"
            "\n"
            "  ⏵⏵ bypass permissions on · esc to interrupt\n"
        )
        s = detect_state(output)
        assert s.state == "thinking"
        assert s.mode == "dangerous"
