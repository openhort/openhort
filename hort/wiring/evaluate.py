"""Wire evaluation engine — checks tool calls against rulesets.

Implements the rule resolution order:
1. Hort-to-hort wire ruleset
2. Fence boundary rulesets (all fences, intersection)
3. Fence inside ruleset (if both in same fence)
4. Llming wire ruleset
5. Direct wire ruleset

Every layer uses the same ``WireRuleset``.  Every layer can only
further restrict — outer layers cannot be weakened by inner layers.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any

from .models import ConversationTaint, FenceConfig, TaintedMessage, ToolGroup, WireRuleset
from .groups import BUILTIN_GROUPS, is_tool_in_group, resolve_groups

logger = logging.getLogger("hort.wiring.evaluate")


@dataclass(frozen=True)
class EvalDecision:
    """Result of evaluating a tool call against rulesets."""

    allowed: bool
    reason: str = ""
    layer: str = ""
    taint_labels: tuple[str, ...] = ()
    blocked_taint: tuple[str, ...] = ()


class WireEvaluator:
    """Evaluates tool calls against stacked rulesets.

    The evaluator is stateless — it receives the full context
    (rulesets, groups, current taint) on each call.
    """

    def __init__(self, groups: dict[str, ToolGroup] | None = None) -> None:
        self._groups = groups or {}

    def check_tool(
        self,
        tool_name: str,
        rulesets: list[tuple[str, WireRuleset]],
        current_taint: set[str] | None = None,
        fences: list[FenceConfig] | None = None,
        source_llming: str = "",
        target_llming: str = "",
    ) -> EvalDecision:
        """Check if a tool call is allowed through stacked rulesets.

        Args:
            tool_name: The tool being called.
            rulesets: List of (layer_name, ruleset) in evaluation order.
            current_taint: Accumulated taint labels in the current zone.
            fences: Fence configs to evaluate.
            source_llming: The llming making the call.
            target_llming: The llming being called.

        Returns:
            EvalDecision with allowed=True/False and reason.
        """
        current_taint = current_taint or set()
        all_taint: list[str] = []
        all_blocked: list[str] = []

        # Evaluate each ruleset in order
        for layer_name, ruleset in rulesets:
            decision = self._check_single(tool_name, ruleset, current_taint, layer_name)
            if not decision.allowed:
                return decision
            all_taint.extend(decision.taint_labels)
            all_blocked.extend(decision.blocked_taint)

        # Evaluate fences
        if fences:
            for fence in fences:
                decision = self._check_fence(
                    tool_name, fence, current_taint,
                    source_llming, target_llming,
                )
                if not decision.allowed:
                    return decision
                all_taint.extend(decision.taint_labels)
                all_blocked.extend(decision.blocked_taint)

        return EvalDecision(
            allowed=True,
            reason="all rulesets passed",
            layer="",
            taint_labels=tuple(all_taint),
            blocked_taint=tuple(all_blocked),
        )

    def _check_single(
        self,
        tool_name: str,
        ruleset: WireRuleset,
        current_taint: set[str],
        layer_name: str,
    ) -> EvalDecision:
        """Evaluate a single ruleset against a tool call."""
        # Check taint blocking first
        if ruleset.block_taint and current_taint:
            blocked = current_taint & set(ruleset.block_taint)
            if blocked:
                return EvalDecision(
                    allowed=False,
                    reason=f"Tainted data blocked: {', '.join(sorted(blocked))}",
                    layer=layer_name,
                    blocked_taint=tuple(sorted(blocked)),
                )

        # Check deny groups
        if ruleset.deny_groups:
            for group_name in ruleset.deny_groups:
                if is_tool_in_group(tool_name, group_name, self._groups):
                    return EvalDecision(
                        allowed=False,
                        reason=f"Tool '{tool_name}' denied by group '{group_name}'",
                        layer=layer_name,
                    )

        # Check explicit deny (glob patterns)
        if ruleset.deny:
            for pattern in ruleset.deny:
                if fnmatch.fnmatch(tool_name, pattern):
                    return EvalDecision(
                        allowed=False,
                        reason=f"Tool '{tool_name}' denied by pattern '{pattern}'",
                        layer=layer_name,
                    )

        # Check allow groups — if specified, tool must be in one
        if ruleset.allow_groups:
            in_any = any(
                is_tool_in_group(tool_name, g, self._groups)
                for g in ruleset.allow_groups
            )
            if not in_any:
                return EvalDecision(
                    allowed=False,
                    reason=f"Tool '{tool_name}' not in any allowed group: {ruleset.allow_groups}",
                    layer=layer_name,
                )

        # Check explicit allow — if specified, tool must match
        if ruleset.allow:
            in_any = any(fnmatch.fnmatch(tool_name, p) for p in ruleset.allow)
            if not in_any:
                return EvalDecision(
                    allowed=False,
                    reason=f"Tool '{tool_name}' not in allow list",
                    layer=layer_name,
                )

        # Collect taint labels
        taint = tuple(ruleset.taint_labels())

        return EvalDecision(
            allowed=True,
            layer=layer_name,
            taint_labels=taint,
        )

    def _check_fence(
        self,
        tool_name: str,
        fence: FenceConfig,
        current_taint: set[str],
        source_llming: str,
        target_llming: str,
    ) -> EvalDecision:
        """Evaluate a fence's rules for a tool call.

        If both source and target are inside the fence, ``inside`` rules apply.
        If only one is inside, ``boundary`` rules apply.
        If neither is inside, the fence is irrelevant.
        """
        src_in = source_llming in fence.members
        tgt_in = target_llming in fence.members

        if not src_in and not tgt_in:
            # Fence doesn't apply
            return EvalDecision(allowed=True)

        if src_in and tgt_in:
            # Both inside — use inside rules
            return self._check_single(
                tool_name, fence.inside, current_taint,
                f"fence:{fence.name}:inside",
            )

        # One inside, one outside — boundary rules
        return self._check_single(
            tool_name, fence.boundary, current_taint,
            f"fence:{fence.name}:boundary",
        )

    def collect_taint(
        self,
        rulesets: list[tuple[str, WireRuleset]],
    ) -> set[str]:
        """Collect all taint labels from a stack of rulesets."""
        labels: set[str] = set()
        for _, ruleset in rulesets:
            labels.update(ruleset.taint_labels())
        return labels

    def prepare_history_for_tool(
        self,
        conversation: ConversationTaint,
        target_ruleset: WireRuleset,
    ) -> list[TaintedMessage]:
        """Prepare conversation history for an LLM tool call.

        Messages whose taint conflicts with the target's
        ``block_taint`` are redacted — the LLM sees a placeholder
        instead of the actual content.  The user always sees
        the full history.

        This enables mixed conversations: the user can ask about
        confidential data AND compose an email in the same chat.
        The email tool only sees the clean messages.
        """
        blocked = set(target_ruleset.block_taint or [])
        return conversation.visible_history(blocked)
