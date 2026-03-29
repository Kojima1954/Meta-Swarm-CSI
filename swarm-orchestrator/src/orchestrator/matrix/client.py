"""Matrix client — connects to Conduit, listens for messages, sends signals."""

from __future__ import annotations

import asyncio
import html
import time
from typing import TYPE_CHECKING, Callable

import structlog
from nio import (
    AsyncClient,
    AsyncClientConfig,
    JoinError,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
    RoomResolveAliasError,
)

from orchestrator.matrix.transcript import TranscriptBuffer, TranscriptEntry
from orchestrator.models.summary import SwarmSummary

if TYPE_CHECKING:
    from orchestrator.config import MatrixConfig, NodeConfig

log = structlog.get_logger()

# Marker prefix to identify our own swarm signal messages
_SIGNAL_MARKER = "\U0001f41d SWARM SIGNAL"


class MatrixBridge:
    """Async bridge to the Matrix homeserver."""

    def __init__(
        self,
        matrix_config: "MatrixConfig",
        node_config: "NodeConfig",
        transcript: TranscriptBuffer,
        on_manual_trigger: Callable[[], None] | None = None,
        allowed_trigger_users: list[str] | None = None,
    ) -> None:
        self._config = matrix_config
        self._node_config = node_config
        self.transcript = transcript
        self._on_manual_trigger = on_manual_trigger
        self._allowed_trigger_users = allowed_trigger_users or []

        client_config = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=False,  # Conduit handles federation; room is unencrypted
        )
        self._client = AsyncClient(
            homeserver=matrix_config.homeserver_url,
            user=matrix_config.user_id,
            config=client_config,
            store_path="/data/nio_store",
        )
        self._room_id: str | None = None
        self._running = False

    async def start(self) -> None:
        """Log in, join the room, and begin syncing."""
        log.info(
            "matrix.login",
            homeserver=self._config.homeserver_url,
            user=self._config.user_id,
        )

        resp = await self._client.login(self._config.password)
        if not isinstance(resp, LoginResponse):
            log.error("matrix.login_failed", response=str(resp))
            raise RuntimeError(f"Matrix login failed: {resp}")

        log.info("matrix.logged_in", user_id=resp.user_id, device_id=resp.device_id)

        # Resolve room alias to room ID
        await self._join_room()

        # Register message callback
        self._client.add_event_callback(self._on_message, RoomMessageText)

        # Start sync loop
        self._running = True
        log.info("matrix.sync_started", room_id=self._room_id)
        await self._client.sync_forever(timeout=30000, full_state=True)

    async def _join_room(self) -> None:
        """Resolve room alias and join."""
        alias = self._config.room_alias
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            resolve_resp = await self._client.room_resolve_alias(alias)
            if isinstance(resolve_resp, RoomResolveAliasError):
                log.warn(
                    "matrix.room_resolve_retry",
                    alias=alias,
                    attempt=attempt,
                    error=str(resolve_resp),
                )
                await asyncio.sleep(min(5 * attempt, 30))
                continue

            self._room_id = resolve_resp.room_id
            join_resp = await self._client.join(self._room_id)
            if isinstance(join_resp, JoinError):
                log.error("matrix.join_failed", room_id=self._room_id, error=str(join_resp))
                raise RuntimeError(f"Failed to join room: {join_resp}")

            log.info("matrix.joined_room", alias=alias, room_id=self._room_id)
            return

        raise RuntimeError(f"Could not resolve room alias {alias} after {max_retries} attempts")

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Handle incoming room messages."""
        if room.room_id != self._room_id:
            return
        # Ignore our own messages
        if event.sender == self._config.user_id:
            return

        body = event.body
        is_signal = body.startswith(_SIGNAL_MARKER)

        entry = TranscriptEntry(
            timestamp=event.server_timestamp / 1000.0 if event.server_timestamp else time.time(),
            sender=room.user_name(event.sender) or event.sender,
            body=body,
            is_swarm_signal=is_signal,
        )
        self.transcript.add(entry)

        # Manual trigger via !summarize command (with authorization check)
        if body.strip().lower() == "!summarize" and self._on_manual_trigger:
            if self._allowed_trigger_users and event.sender not in self._allowed_trigger_users:
                log.warn("matrix.unauthorized_trigger", sender=event.sender)
                return
            log.info("matrix.manual_trigger", sender=event.sender)
            self._on_manual_trigger()

    async def send_swarm_signal(
        self, summary: SwarmSummary, source_node_name: str
    ) -> None:
        """Inject a formatted Swarm Signal into the deliberation room."""
        if not self._room_id:
            log.error("matrix.send_failed", reason="no room joined")
            return

        plain = _format_signal_plain(summary, source_node_name)
        html = _format_signal_html(summary, source_node_name)

        await self._client.room_send(
            room_id=self._room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": plain,
                "format": "org.matrix.custom.html",
                "formatted_body": html,
            },
        )
        log.info(
            "matrix.signal_sent",
            source=source_node_name,
            round=summary.round_number,
        )

    async def send_text(self, text: str) -> None:
        """Send a plain text message to the room."""
        if not self._room_id:
            return
        await self._client.room_send(
            room_id=self._room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )

    async def stop(self) -> None:
        """Gracefully shut down the Matrix client."""
        self._running = False
        await self._client.close()
        log.info("matrix.stopped")


def _format_signal_plain(summary: SwarmSummary, source_name: str) -> str:
    lines = [
        f"\U0001f41d SWARM SIGNAL from {source_name} (Round {summary.round_number}):",
        "\u2501" * 40,
    ]
    lines.append("\U0001f4cc Key Positions:")
    for pos in summary.key_positions:
        lines.append(f"  \u2022 {pos}")
    if summary.emerging_consensus:
        lines.append(f"\n\U0001f91d Emerging Consensus:\n  {summary.emerging_consensus}")
    if summary.dissenting_views:
        lines.append("\n\u26a1 Dissenting Views:")
        for view in summary.dissenting_views:
            lines.append(f"  \u2022 {view}")
    if summary.open_questions:
        lines.append("\n\u2753 Open Questions:")
        for q in summary.open_questions:
            lines.append(f"  \u2022 {q}")
    lines.append("\u2501" * 40)
    return "\n".join(lines)


def _format_signal_html(summary: SwarmSummary, source_name: str) -> str:
    esc = html.escape
    positions = "".join(f"<li>{esc(p)}</li>" for p in summary.key_positions)
    sections = [
        f"<h4>\U0001f41d SWARM SIGNAL from {esc(source_name)} (Round {summary.round_number})</h4>",
        "<hr/>",
        f"<p><strong>\U0001f4cc Key Positions:</strong></p><ul>{positions}</ul>",
    ]
    if summary.emerging_consensus:
        sections.append(
            f"<p><strong>\U0001f91d Emerging Consensus:</strong><br/>{esc(summary.emerging_consensus)}</p>"
        )
    if summary.dissenting_views:
        dissent = "".join(f"<li>{esc(v)}</li>" for v in summary.dissenting_views)
        sections.append(f"<p><strong>\u26a1 Dissenting Views:</strong></p><ul>{dissent}</ul>")
    if summary.open_questions:
        questions = "".join(f"<li>{esc(q)}</li>" for q in summary.open_questions)
        sections.append(f"<p><strong>\u2753 Open Questions:</strong></p><ul>{questions}</ul>")
    sections.append("<hr/>")
    return "\n".join(sections)
