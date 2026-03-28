"""Tests for encryption (PyNaCl SealedBox)."""

from __future__ import annotations

import base64
import json

import pytest
from nacl.public import PrivateKey

from orchestrator.federation.crypto import decrypt, encrypt_for_nodes
from orchestrator.models.topology import SwarmNode


@pytest.fixture
def keypair():
    key = PrivateKey.generate()
    return key, key.public_key


@pytest.fixture
def recipient_node(keypair):
    _, pub = keypair
    return SwarmNode(
        id="node-beta",
        name="Node Beta",
        domain="beta.test",
        public_key=base64.b64encode(bytes(pub)).decode(),
        role="participant",
        is_self=False,
    )


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self, keypair, recipient_node):
        private_key, _ = keypair
        plaintext = b'{"test": "data"}'

        encrypted = encrypt_for_nodes(plaintext, [recipient_node])
        assert "node-beta" in encrypted

        decrypted = decrypt(encrypted["node-beta"], private_key)
        assert decrypted == plaintext

    def test_encrypt_for_multiple_recipients(self):
        keys = [(PrivateKey.generate(),) for _ in range(3)]
        nodes = []
        for i, (priv,) in enumerate(keys):
            pub = priv.public_key
            nodes.append(
                SwarmNode(
                    id=f"node-{i}",
                    domain=f"n{i}.test",
                    public_key=base64.b64encode(bytes(pub)).decode(),
                    role="participant",
                    is_self=False,
                )
            )

        plaintext = json.dumps({"round": 1}).encode()
        encrypted = encrypt_for_nodes(plaintext, nodes)

        assert len(encrypted) == 3
        for i, (priv,) in enumerate(keys):
            decrypted = decrypt(encrypted[f"node-{i}"], priv)
            assert decrypted == plaintext

    def test_skip_node_without_key(self):
        node = SwarmNode(
            id="no-key",
            domain="test",
            public_key="",
            role="participant",
            is_self=False,
        )
        encrypted = encrypt_for_nodes(b"data", [node])
        assert "no-key" not in encrypted

    def test_decrypt_with_wrong_key_fails(self, recipient_node):
        plaintext = b"secret"
        encrypted = encrypt_for_nodes(plaintext, [recipient_node])

        wrong_key = PrivateKey.generate()
        with pytest.raises(Exception):
            decrypt(encrypted["node-beta"], wrong_key)

    def test_ciphertext_is_different_each_time(self, recipient_node):
        plaintext = b"same input"
        enc1 = encrypt_for_nodes(plaintext, [recipient_node])
        enc2 = encrypt_for_nodes(plaintext, [recipient_node])
        # SealedBox uses ephemeral keys, so ciphertexts differ
        assert enc1["node-beta"] != enc2["node-beta"]
