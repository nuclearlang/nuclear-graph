"""Documents are stored encrypted (AES-256-GCM); only the graph's process, which holds the key, reads them."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Box:
    def __init__(self, key: bytes) -> None:
        self._aes = AESGCM(key)

    def seal(self, text: str) -> str:
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self._aes.encrypt(nonce, text.encode(), None)).decode()

    def open(self, sealed: str) -> str:
        raw = base64.b64decode(sealed)
        return self._aes.decrypt(raw[:12], raw[12:], None).decode()
