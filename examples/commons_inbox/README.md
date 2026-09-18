Drop JSON receipts from this folder into `data/commons_inbox/` to test the local
Commons adapter.

Example flow:

```bash
mkdir -p data/commons_inbox
cp examples/commons_inbox/sample_inference_receipt.json data/commons_inbox/
cp examples/commons_inbox/sample_verifier_receipt.json data/commons_inbox/
python scripts/run_commons_adapter.py --once --json
```

Notes:

- These are schema-shaped fixtures for adapter testing.
- A receipt may still be rejected if its `ticket_id` does not exist in your live database.
- Accepted and rejected payloads are archived under `data/commons_archive/`.
