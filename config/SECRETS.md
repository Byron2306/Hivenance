# Local secret handling

The Phase-0 package intentionally contains no API credentials or reusable encryption key.

Preferred: provide exchange credentials through environment variables. Alternatively, copy
`api_keys.example.json` to `api_keys.json`; the latter is ignored by Git. Disable withdrawal
permissions on every exchange key and restrict keys by IP where the venue supports it.

`SecurityAgent` creates `config/encryption.key` locally on first use. That file is ignored and
must never be committed or included in support archives.
