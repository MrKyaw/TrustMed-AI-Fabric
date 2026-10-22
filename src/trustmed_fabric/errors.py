"""Domain errors with stable, machine-readable codes."""

from __future__ import annotations

from typing import Any


class FabricError(Exception):
    code = "FABRIC_ERROR"
    status_code = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFoundError(FabricError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(FabricError):
    code = "CONFLICT"
    status_code = 409


class ValidationError(FabricError):
    code = "VALIDATION_ERROR"
    status_code = 422


class PolicyDeniedError(FabricError):
    code = "POLICY_DENIED"
    status_code = 422
