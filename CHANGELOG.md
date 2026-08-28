# Changelog

## 1.0.2 — 2026-08-27

- Use a verified no-follow directory descriptor for all state reads, writes, and deletion
- Replace predictable temporary state paths with securely created private files
- Reject non-regular, linked, oversized, or foreign-owned state files
- Bound camera/system counts, remote field lengths, errors, stdin, cache, and JSON output
- Cap arm/disarm actions and total network-operation time
- Discard library stderr before it reaches Quickshell's long-lived collectors
- Cancel pending authentication when the panel closes
- Document inherited BlinkPy live-transport trust limitations
- Add regression tests for directory/file symlinks, FIFOs, oversized input, permissions, and model limits

## 1.0.1 — 2026-08-27

- Hash-lock the complete `uv` runtime dependency graph
- Render Blink-controlled camera names and errors strictly as plain text
- Stop the live player and helper before disconnecting and deleting saved state

## 1.0.0 — 2026-08-26

- Initial public release
- Blink email/password and 2FA onboarding
- Armed state, battery, temperature, and motion information
- Arm/disarm controls
- Embedded on-demand live view
- Automatic `uv` dependency management
