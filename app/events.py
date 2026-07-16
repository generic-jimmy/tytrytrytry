"""In-process pub/sub event broker for WebSocket live updates.

The bot emits events when moderation actions happen (member joins, message
flagged, appeal filed, etc.). Dashboard clients connected via WebSocket
subscribe to a group's channel and receive those events in real-time,
updating badges and toasts without polling.

Single-process by design — fine for the one-container deployment model
this bot is built for. If you ever scale to multiple instances, move this
to Redis pub/sub (same interface, different backend).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("telegram_bot.events")

# Per-group set of subscriber queues. Each connected WebSocket gets its own
# asyncio.Queue; events are broadcast to all queues for that group.
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

# Ring buffer of recent events per group, so newly-connected clients can
# catch up on the last N events immediately on connect.
_RECENT_BUFFER_SIZE = 20
_recent_events: dict[int, list[dict]] = defaultdict(list)


def emit(group_id: int, event_type: str, payload: dict | None = None) -> None:
    """Fire-and-forget event emission. Called from bot handlers and API
    routes whenever something interesting happens.

    Safe to call from sync or async contexts — uses call_soon_threadsafe
    internally to schedule the actual broadcast on the running loop.
    """
    event = {
        "type": event_type,
        "group_id": group_id,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_broadcast(group_id, event))
    except RuntimeError:
        # No running loop (called from sync code at import time, etc.)
        # fall back to queuing onto the loop once it's running.
        logger.debug("emit() called with no running loop — event dropped: %s", event_type)


async def _broadcast(group_id: int, event: dict) -> None:
    """Pushes the event to every subscriber queue for this group, and
    appends it to the recent-events ring buffer."""
    _recent_events[group_id].append(event)
    if len(_recent_events[group_id]) > _RECENT_BUFFER_SIZE:
        _recent_events[group_id] = _recent_events[group_id][-_RECENT_BUFFER_SIZE:]

    subs = list(_subscribers.get(group_id, set()))
    dead: list[asyncio.Queue] = []
    for q in subs:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Subscriber is too slow — drop the event rather than block.
            dead.append(q)
    for q in dead:
        _subscribers[group_id].discard(q)


async def subscribe(group_id: int) -> asyncio.Queue:
    """Creates a subscriber queue for the given group. The WebSocket
    handler reads from this queue and forwards events to the client.
    Returns the queue + a list of recent events for immediate replay."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[group_id].add(q)
    recent = list(_recent_events.get(group_id, []))
    return q, recent


def unsubscribe(group_id: int, q: asyncio.Queue) -> None:
    """Removes a subscriber queue. Called when the WebSocket disconnects."""
    _subscribers[group_id].discard(q)


def subscriber_count(group_id: int) -> int:
    return len(_subscribers.get(group_id, set()))


def total_subscriber_count() -> int:
    """Sum of connected WebSocket subscribers across every group — what the
    /health endpoint actually wants, as opposed to subscriber_count(0),
    which only ever checked a group literally ID'd 0 (never a real
    Telegram chat) and so always read zero regardless of real traffic."""
    return sum(len(subs) for subs in _subscribers.values())


# --------------------------------------------------------- convenience helpers

def emit_member_joined(group_id: int, user_id: int, full_name: str, status: str) -> None:
    emit(group_id, "member_joined", {
        "user_id": user_id, "full_name": full_name, "status": status,
    })


def emit_purgatory_decision(group_id: int, entry_id: int, user_id: int, decision: str) -> None:
    emit(group_id, "purgatory_decided", {
        "entry_id": entry_id, "user_id": user_id, "decision": decision,
    })


def emit_message_flagged(group_id: int, flag_id: int, user_id: int, category: str, severity: str) -> None:
    emit(group_id, "message_flagged", {
        "flag_id": flag_id, "user_id": user_id,
        "category": category, "severity": severity,
    })


def emit_appeal_filed(group_id: int, appeal_id: int, user_id: int, target_action: str) -> None:
    emit(group_id, "appeal_filed", {
        "appeal_id": appeal_id, "user_id": user_id, "target_action": target_action,
    })


def emit_mod_action(group_id: int, action: str, target_user_id: int, reason: str) -> None:
    emit(group_id, "mod_action", {
        "action": action, "target_user_id": target_user_id, "reason": reason,
    })


def emit_raid_alert(group_id: int, join_count: int, window_minutes: int) -> None:
    emit(group_id, "raid_alert", {
        "join_count": join_count, "window_minutes": window_minutes,
    })


def emit_banned_rejoin(group_id: int, user_id: int, full_name: str, original_ban_action: str) -> None:
    emit(group_id, "banned_rejoin", {
        "user_id": user_id, "full_name": full_name,
        "original_ban_action": original_ban_action,
    })


def emit_settings_changed(group_id: int, fields: list[str]) -> None:
    emit(group_id, "settings_changed", {"fields": fields})
