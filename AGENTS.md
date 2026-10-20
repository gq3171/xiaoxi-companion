# Xiaoxi repository instructions

- Read `docs/INSTALL_FOR_AGENTS.md` before deploying. `install.sh` defaults to read-only; initial install and reviewed upgrades are different workflows.
- Never read out, commit or paste private env files, sdkconfig, tokens, private hosts, recordings or runtime state. Examples must use placeholders. See `SECURITY.md`.
- The authoritative brain entry points are `computer/agent.py`, `computer/brain.py`, and `computer/companion.py` (`desktop-v1`). Do not deploy historical patches or infer success from outdated notes.
- Web and firmware share `pet_scene*.c`, `pet_home.c`, frame indices and layout. Update contracts on both sides; do not add independent simulated web life.
- User-visible success requires actual execution evidence. Cancellation must fence late model results; recovery must not automatically repeat unknown side effects.
- Follow `docs/DEVELOPMENT.md` for tests. Unit tests do not replace real microphone, screen, touch, rotation and noVNC acceptance.
- Do not alter a running deployment, flash a device or perform external account actions just to run tests. Use isolated fixtures and temporary paths.
