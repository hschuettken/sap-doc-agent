"""Spec2Sphere tenant module — context envelope, policy stack, RBAC, workspace."""

from spec2sphere.tenant.context import ContextEnvelope, ResolvedPolicyStack, ScopedQuery
from spec2sphere.tenant.policy import resolve_policy, get_policy_stack

__all__ = [
    "ContextEnvelope",
    "ResolvedPolicyStack",
    "ScopedQuery",
    "resolve_policy",
    "get_policy_stack",
]
