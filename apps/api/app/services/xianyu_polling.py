from __future__ import annotations

import random


class XianyuPollFlowControlled(RuntimeError):
    """The platform asked the low-frequency history fallback to back off."""


def next_fallback_poll_delay(
    current_delay: float,
    *,
    recovered: int = 0,
    flow_controlled: bool = False,
    failed: bool = False,
) -> float:
    """Choose a fast-but-conservative delay for the history safety net."""
    if flow_controlled:
        return min(max(current_delay * 2, 180.0), 900.0)
    if failed:
        return min(max(current_delay * 2, 90.0), 600.0)
    if recovered:
        return 15.0
    if current_delay < 45.0:
        return 45.0
    return min(current_delay + 15.0, 75.0)


def jittered_poll_delay(delay: float) -> float:
    """Avoid synchronized, machine-perfect polling without large latency swings."""
    return max(10.0, delay * random.uniform(0.9, 1.1))


def select_changed_conversation_items(
    parsed_items: list[tuple[dict, dict]],
    signatures: dict[str, str],
    *,
    seeded: bool,
    limit: int = 6,
) -> list[tuple[dict, dict]]:
    """Select only conversations whose newest-message signature changed."""
    candidates: list[tuple[dict, dict]] = []
    for raw_item, parsed in parsed_items:
        cid = str(parsed.get("cid") or "")
        signature = str(parsed.get("last_message_signature") or "")
        previous = signatures.get(cid)
        changed = previous != signature and (seeded or previous is not None)
        if not seeded and previous is None:
            changed = len(candidates) < limit
        signatures[cid] = signature
        if changed and len(candidates) < limit:
            candidates.append((raw_item, parsed))
    return candidates
