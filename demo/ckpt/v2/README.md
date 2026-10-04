# Demo F identities (protocol v2) — DEMO VALUES, NOT SECRETS

`owner.key`, `registry.key` and `seed.json` are encrypted with the **public** passphrase
`sigil-demo-only-passphrase` (written in `../../08_protocol_v2.py`). They're committed on purpose so the
saved results in `../../results/protocol_v2*` reproduce, exactly like `../owner_secret.json` for the v1
demos. Anyone with the repository can act as this owner. Never reuse them; for real use run
`sigil keygen` and `sigil seed`, which keep keys under `secrets/` (gitignored) with your own passphrase.

`python 08_protocol_v2.py --retrain` replaces all of them with fresh ones.
