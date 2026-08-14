# Integration Tests

Integration tests may call public APIs, so keep them separate from deterministic unit tests.

Initial target:

1. Fetch a small known page for the configured research account.
2. Save the raw payload.
3. Normalize supported records.
4. Persist and reload the normalized data.
5. Verify count and key-field consistency.

Do not put credentials or private wallet material in integration tests.
