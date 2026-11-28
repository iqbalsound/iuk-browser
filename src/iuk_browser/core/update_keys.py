"""Public keys that may sign update manifests (base64, raw Ed25519).

Generate a pair with `python packaging/tools/gen_update_key.py`: keep the private key in the GitHub secret
UPDATE_SIGNING_KEY and paste the public key here before you publish your first release.
"""
UPDATE_PUBLIC_KEYS: list[str] = []

# Where the signed manifests are published (GitHub Pages of your repository).
UPDATE_BASE_URL = "https://iqbalsound.github.io/iuk-browser/update"
