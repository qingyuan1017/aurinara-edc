"""Client contract for the separately deployed custom-function sandbox.

This module intentionally contains no Python evaluation primitive. The API can
only submit work to an explicitly configured runtime and fails closed otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError, ValidationError

_ALLOWED_COMMANDS = frozenset({"set_value", "clear_value", "open_query", "show", "hide", "require"})


@dataclass(frozen=True)
class RuntimeResult:
    runtime_execution_id: str | None
    status: str
    result: Any
    commands: list[dict[str, Any]]
    error_code: str | None
    duration_ms: int | None


class CustomFunctionRuntimeClient:
    """Submit execution to a network-isolated runtime service."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    async def execute(
        self,
        *,
        function_version_id: str,
        source_code: str,
        source_sha256: str,
        entrypoint: str,
        inputs: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> RuntimeResult:
        settings = self.settings
        if not settings.custom_function_runtime_enabled or not settings.custom_function_runtime_url:
            raise ServiceUnavailableError(
                "Custom function runtime is not enabled",
                details={"reason": "CUSTOM_FUNCTION_RUNTIME_DISABLED"},
            )

        input_bytes = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        if len(input_bytes) > settings.custom_function_max_input_bytes:
            raise ValidationError(
                "Custom function input is too large",
                details={"max_bytes": settings.custom_function_max_input_bytes},
            )

        headers = {"Content-Type": "application/json"}
        if settings.custom_function_runtime_token is not None:
            headers["Authorization"] = (
                f"Bearer {settings.custom_function_runtime_token.get_secret_value()}"
            )
        request_body = {
            "function_version_id": function_version_id,
            "language": "python",
            "source_code": source_code,
            "source_sha256": source_sha256,
            "entrypoint": entrypoint,
            "inputs": inputs,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "limits": {
                "timeout_ms": settings.custom_function_execution_timeout_ms,
                "memory_mb": settings.custom_function_memory_limit_mb,
                "output_bytes": settings.custom_function_max_output_bytes,
                "network": "disabled",
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.custom_function_runtime_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{settings.custom_function_runtime_url.rstrip('/')}/v1/executions",
                    headers=headers,
                    json=request_body,
                )
                response.raise_for_status()
                if len(response.content) > settings.custom_function_max_output_bytes:
                    raise ValidationError("Custom function runtime output is too large")
                payload = response.json()
        except ValidationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ServiceUnavailableError(
                "Custom function runtime request failed",
                details={"reason": "CUSTOM_FUNCTION_RUNTIME_UNAVAILABLE"},
            ) from exc

        if not isinstance(payload, dict) or payload.get("status") not in {"succeeded", "failed"}:
            raise ServiceUnavailableError(
                "Custom function runtime returned an invalid response",
                details={"reason": "CUSTOM_FUNCTION_RUNTIME_INVALID_RESPONSE"},
            )
        commands = payload.get("commands", [])
        if not isinstance(commands, list) or any(
            not isinstance(command, dict) or command.get("type") not in _ALLOWED_COMMANDS
            for command in commands
        ):
            raise ValidationError(
                "Custom function returned an unsupported command",
                details={"reason": "CUSTOM_FUNCTION_COMMAND_NOT_ALLOWED"},
            )
        duration_ms = payload.get("duration_ms")
        if duration_ms is not None and (not isinstance(duration_ms, int) or duration_ms < 0):
            raise ServiceUnavailableError("Custom function runtime returned an invalid response")
        return RuntimeResult(
            runtime_execution_id=(
                str(payload["execution_id"]) if payload.get("execution_id") is not None else None
            ),
            status=str(payload["status"]),
            result=payload.get("result"),
            commands=commands,
            error_code=(str(payload["error_code"])[:80] if payload.get("error_code") else None),
            duration_ms=duration_ms,
        )


custom_function_runtime_client = CustomFunctionRuntimeClient()

__all__ = ["CustomFunctionRuntimeClient", "RuntimeResult", "custom_function_runtime_client"]
