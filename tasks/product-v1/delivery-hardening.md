# Further delivery hardening

User asked what more can be done for delivery. Continue reversible evidence and
make the owner-required privacy review concrete before requesting a decision.

Plan: audit public source bypass; prepare #1288 publication/identity design;
run the existing full quality-only gate; retain failures and exact command hashes;
update the release packet instead of promoting it on targeted CI alone.

Findings: public repository exposes all four current latest ledgers and CN_27
operating lineage anonymously. Pages-only redaction cannot close this boundary.
Immutable source hashes also prevent silently editing a shipped lineage copy.

Progress: 5/5 anonymous source requests confirmed, value-free receipt retained;
proposal prepared for explicit owner design review. Full release quality run is
in progress at the W4 source revision 266a8c192, in ignored local artifacts.
Initial full backend collection encountered protobuf MemoryError followed by a
partially initialized MLflow error; classify after isolated reproduction, not
as a proven dependency regression or a passed gate. No prod/state/policy mutation.
