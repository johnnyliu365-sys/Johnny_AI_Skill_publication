from __future__ import annotations

import json, math, re, subprocess
from typing import TypeVar
from pydantic import BaseModel, ValidationError
from .host_contracts import (CodexBlockReason, CodexBlocked, CodexCliVersion, CodexCommandPort,
    CodexCommandResponse, CodexFilesystemPort, CodexMarketplaceList, CodexPluginList,
    CodexPreflightEligible, CodexPreflightRequest, CodexPreflightResult, CodexSourceProof)

Model = TypeVar("Model", bound=BaseModel)


class _Failure(Exception):
    def __init__(self, reason: CodexBlockReason) -> None: super().__init__(reason.value); self.reason = reason


class ProcessCodexCommandPort:
    def execute(self, arguments: tuple[str, ...], timeout_seconds: float) -> CodexCommandResponse:
        result = subprocess.run(arguments, shell=False, capture_output=True, text=False, timeout=timeout_seconds, check=False)
        return CodexCommandResponse(exit_code=result.returncode, stdout=result.stdout.decode("utf-8"), stderr=result.stderr.decode("utf-8"))


class CodexCliPreflight:
    def __init__(self, command_port: CodexCommandPort, filesystem_port: CodexFilesystemPort, timeout_seconds: float = 15.0) -> None:
        self._command, self._filesystem, self._timeout = command_port, filesystem_port, timeout_seconds
        self._ports = isinstance(command_port, CodexCommandPort) and isinstance(filesystem_port, CodexFilesystemPort)

    def check(self, request: CodexPreflightRequest) -> CodexPreflightResult:
        try:
            request = self._valid(request, CodexPreflightRequest)
            try: timeout_ok = math.isfinite(self._timeout) and self._timeout > 0
            except (TypeError, ValueError): timeout_ok = False
            if not self._ports or not timeout_ok: raise _Failure(CodexBlockReason.INVALID_PORT)
            version = self._version()
            proof = self._source(request)
            if proof.installation_id != request.installation_id or proof.root != request.root or proof.locator != request.marketplace_source:
                raise _Failure(CodexBlockReason.SOURCE_MISMATCH)
            markets = self._parse(self._run(("codex", "plugin", "marketplace", "list", "--json")), CodexMarketplaceList).marketplaces
            plugins = self._parse(self._run(("codex", "plugin", "list", "--available", "--json")), CodexPluginList)
            names = {entry.name.casefold() for entry in markets}
            if request.marketplace.value.casefold() in names or any(entry.name.casefold() == request.plugin.value.casefold() for entry in plugins.installed + plugins.available):
                raise _Failure(CodexBlockReason.COLLISION)
            return CodexPreflightEligible(version=version)
        except _Failure as failure: return CodexBlocked(reason=failure.reason)
        except (ValidationError, TypeError, ValueError, AttributeError): return CodexBlocked(reason=CodexBlockReason.INVALID_INPUT)
        except OSError: return CodexBlocked(reason=CodexBlockReason.FILESYSTEM_FAILED)

    def _version(self) -> CodexCliVersion:
        text = self._run(("codex", "--version")).stdout.strip()
        match = re.fullmatch(r"codex-cli (\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?)", text)
        if match is None: raise _Failure(CodexBlockReason.UNSUPPORTED_CLI)
        return CodexCliVersion(value=match.group(1))

    def _source(self, request: CodexPreflightRequest) -> CodexSourceProof:
        try: return CodexSourceProof.model_validate_json(self._filesystem.resolve_source(request).model_dump_json(warnings=False))
        except (ValidationError, TypeError, ValueError, AttributeError): raise _Failure(CodexBlockReason.SOURCE_MISMATCH)

    def _run(self, arguments: tuple[str, ...]) -> CodexCommandResponse:
        try:
            response = self._command.execute(arguments, self._timeout)
            response = CodexCommandResponse.model_validate_json(response.model_dump_json(warnings=False))
            if response.exit_code != 0: raise _Failure(CodexBlockReason.COMMAND_FAILED)
            return response
        except UnicodeError: raise _Failure(CodexBlockReason.INVALID_ENCODING)
        except subprocess.TimeoutExpired: raise _Failure(CodexBlockReason.TIMEOUT)
        except FileNotFoundError: raise _Failure(CodexBlockReason.EXECUTABLE_UNAVAILABLE)
        except PermissionError: raise _Failure(CodexBlockReason.ACCESS_DENIED)
        except OSError: raise _Failure(CodexBlockReason.COMMAND_FAILED)

    def _parse(self, response: CodexCommandResponse, model: type[Model]) -> Model:
        try: return model.model_validate(json.loads(response.stdout))
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError): raise _Failure(CodexBlockReason.MALFORMED_OUTPUT)

    def _valid(self, value: object, model: type[Model]) -> Model:
        if not isinstance(value, BaseModel): raise TypeError("typed input required")
        return model.model_validate_json(value.model_dump_json(warnings=False))
