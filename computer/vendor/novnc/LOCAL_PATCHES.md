# Local noVNC integration patches (2026-10-20)

The vendored sources retain their MPL 2.0 headers and Debian copyright record.

- `core/rfb.js`: optional constructor `enableH264:false` omits encoding 50; default remains enabled when WebCodecs supports it. Xiaoxi opts out in both view/control channels. This avoids a plausible browser-specific frozen-render path described in https://github.com/novnc/noVNC/pull/2074 (open at inspection; this is not that unmerged patch).
- `core/display.js`: content-free `renderRevision` advances only after a damaged region is drawn to the visible canvas.
- `core/rfb.js`: read-only `renderingState` returns `{pending,revision}`. Application watchdog blocks input after >4 seconds of unchanged pending rendering and reconnects after >8 seconds. Healthy continuous painting and an idle desktop do not trigger it. No screen contents, keys, coordinates or identifiers are collected. Background resume requests a fresh connection/full framebuffer; clicks are never replayed.

Tests: `computer/test_novnc_render.cjs`, `computer/test_desktop_client.cjs`.
This is a compatibility mitigation; real Windows acceptance is tracked separately.
