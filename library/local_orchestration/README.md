# Local orchestration module

This package provides strongly typed, fail-closed contracts and pure planning/reducer components
for local Codex registration, proof settlement, compensation and guarded project operations.

## Public boundary

- `contracts.py`, `host_contracts.py`, `runtime_contracts.py`: domain contracts and finite states.
- `ports.py`, `codex_registration_port.py`, `codex_compensation_port.py`: explicit effect ports.
- `*_reducer.py`, `*_composition.py`, `*_settlement*.py`: pure decisions and exact proof binding.
- `codex_cli_adapter.py`, `guarded_git.py`, `installation.py`: guarded adapters; never admitted by
  catalog selection alone.

Adoption requires the target project's own approved SPEC and ticket. Catalog selection does not
authorize installation, host mutation, target-project writes, Git effects, network access or
Secret handling.
