# Fixtures

Recorded, sanitized `get_window_state` payloads of the `CuaTestHarness.AppKit` test app, copied unchanged from
`cua-J/libs/cua-driver/examples/jev-use/fixtures/native/` ([cua-J](https://github.com/geekjapan/cua-J), an import of [trycua/cua](https://github.com/trycua/cua)).

- `appkit-window-state-initial-v1.json`: window before any action.
- `appkit-window-state-after-actions-v1.json`: window after Increment, the checkbox, Save note ("hello jev") and the Large radio.

Screenshots and `tree_markdown` were removed upstream. Tests only replay them; nothing here launches cua-driver.

These files are Copyright (c) 2025 Cua AI, Inc. and Copyright (c) 2026 geekjapan, under the MIT License in
the repository's LICENSE file.
