# Security

Security requirements:

- BYOK keys encrypted at rest with AES-256-GCM
- Decrypted provider keys are never returned to browsers after save
- Trace redaction runs before persistence
- Paid models require explicit per-request `allow_paid: true`
- Peer completions are untrusted data and are fenced in XML
- Audit log is append-only and partitioned monthly
- Self-hosted telemetry is opt-in only

The current scaffold includes redaction patterns and the prompt-injection fencing contract. Hosted KMS/keyring integration belongs to the later hosted tier phase.
