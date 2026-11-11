# Hacklipse recovery terminal

Run `python app.py` and open http://localhost:8000/submit.
Runtime dependencies: Flask and waitress.

Set `CTF_FLAGS_JSON` to a JSON array of exactly 15 unique flags before starting the server.
Do not commit actual flags. If unset, the interface remains available but validation returns 503.
Keep the flag list order stable after submissions begin: its positions identify solved flags internally, not passage fragments.

Every new distinct correct flag reveals the next passage fragment, regardless of flag order.
Progress is stored in `instance/progress.sqlite3`, linked to a signed browser cookie (31-day default lifetime).
Clearing cookies or switching browsers starts another participant session. This is not an account/login system.
Back up the instance directory, including the signing key, to preserve progress.
Use a separate deployment from intentionally vulnerable challenges.

After all 15 English fragments finish displaying, the title The Moon and Sixpence
and author W. Somerset Maugham appear below the completed passage.
