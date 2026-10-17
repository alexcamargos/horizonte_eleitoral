"""Serializacao canonica e identificadores deterministas sem efeitos colaterais."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import Enum

from horizonte_eleitoral.domain.errors import ValidationError


def canonical_json_bytes(value: object) -> bytes:
    """Serializa valores de dominio de modo estavel para hashes e arquivos imutaveis."""
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidationError("O valor nao pode ser serializado canonicamente.") from error


def sha256_hex(value: bytes) -> str:
    """Retorna o hash SHA-256 hexadecimal de bytes imutaveis."""
    return hashlib.sha256(value).hexdigest()


def deterministic_id(namespace: str, payload: Mapping[str, object]) -> str:
    """Gera identificador com namespace a partir de uma representacao canonica."""
    if not namespace or ":" in namespace:
        raise ValidationError(
            "O namespace do identificador deve ser nao vazio e nao conter dois-pontos."
        )
    return f"{namespace}:{sha256_hex(canonical_json_bytes(payload))}"


def require_sha256(value: str, field_name: str) -> str:
    """Valida e normaliza um hash SHA-256 hexadecimal."""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError(f"{field_name} deve conter um SHA-256 hexadecimal em minusculas.")
    return value


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value
