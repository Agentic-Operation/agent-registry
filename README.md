# Agent Registry

Production Agent Card Registry for Spec-445. Implements the API contract canonically defined in
[agent-discovery-card/api/openapi/registry-api.yaml](https://github.com/Agentic-Operation/agent-discovery-card/blob/main/api/openapi/registry-api.yaml):
card register (validated via agent-conformance), search by skill/autonomy/impact/status, versioned GET,
integrity verify, per-environment instance registration (`environment-instances`), WoA discovery at
`/.well-known/woa.json`.

- Run: `python src/registry/registry.py --port 8080 --store cards.json` (needs an `agent-conformance`
  checkout for validators: `AGENT_CONFORMANCE=/path/to/agent-conformance`)
- Tests: `pytest tests` (smoke-registers the worked example card from agent-discovery-card@main)
- Spec repos: agent-profile-management · agent-bootstrap-management · agent-discovery-card · docs: agent-standard-docs
- License: Apache-2.0
