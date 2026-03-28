"""Encryption — X25519 SealedBox via PyNaCl."""

from __future__ import annotations

import base64
from pathlib import Path

import structlog
from nacl.public import PrivateKey, PublicKey, SealedBox

from orchestrator.models.topology import SwarmNode

log = structlog.get_logger()


def load_keypair(private_path: str, public_path: str) -> tuple[PrivateKey, PublicKey]:
    """Load an X25519 keypair from base64-encoded files."""
    priv_bytes = base64.b64decode(Path(private_path).read_text().strip())
    pub_bytes = base64.b64decode(Path(public_path).read_text().strip())
    private_key = PrivateKey(priv_bytes)
    public_key = PublicKey(pub_bytes)
    log.info("crypto.keypair_loaded")
    return private_key, public_key


def encrypt_for_nodes(
    plaintext: bytes,
    recipients: list[SwarmNode],
) -> dict[str, str]:
    """Encrypt plaintext for each recipient using SealedBox.

    Returns a dict of {node_id: base64_ciphertext}.
    """
    result: dict[str, str] = {}
    for node in recipients:
        if not node.public_key:
            log.warn("crypto.skip_no_key", node_id=node.id)
            continue
        pub_bytes = base64.b64decode(node.public_key)
        pub_key = PublicKey(pub_bytes)
        sealed_box = SealedBox(pub_key)
        ciphertext = sealed_box.encrypt(plaintext)
        result[node.id] = base64.b64encode(ciphertext).decode()
    return result


def decrypt(ciphertext_b64: str, private_key: PrivateKey) -> bytes:
    """Decrypt a base64-encoded SealedBox ciphertext."""
    ciphertext = base64.b64decode(ciphertext_b64)
    sealed_box = SealedBox(private_key)
    return sealed_box.decrypt(ciphertext)
