"""Wiring model — unified rulesets, fences, groups, and credential resolution.

The wiring module implements the security model described in the docs:
two concepts (llmings and horts), four wiring forms (llming-to-hort,
hort-to-hort, direct llming-to-llming, fence), and one unified
``WireRuleset`` used across all of them.

Quick start::

    from hort.wiring import WireRuleset, WireEvaluator, ToolGroup

    ruleset = WireRuleset(allow_groups=["read"], deny_groups=["destroy"])
    evaluator = WireEvaluator(groups={"read": ToolGroup(auto=["read_*", "get_*"])})
    decision = evaluator.is_tool_allowed("read_email", [ruleset])
"""

from .models import (
    ConversationTaint,
    CredentialRef,
    FenceConfig,
    HortDef,
    LlmingConnection,
    TaintedMessage,
    ToolGroup,
    WireRuleset,
    WorldConfig,
)
from .credentials import resolve_credential
from .groups import resolve_groups, auto_assign_group, BUILTIN_GROUPS
from .evaluate import WireEvaluator

__all__ = [
    "ConversationTaint",
    "CredentialRef",
    "FenceConfig",
    "HortDef",
    "LlmingConnection",
    "TaintedMessage",
    "ToolGroup",
    "WireRuleset",
    "WorldConfig",
    "WireEvaluator",
    "resolve_credential",
    "resolve_groups",
    "auto_assign_group",
    "BUILTIN_GROUPS",
]
