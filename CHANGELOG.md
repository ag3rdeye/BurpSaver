# Changelog

All notable changes to BurpSaver are documented here.

---

## [5.8.0] — 2026-05-27

### Fixed — Root cause of `array('b', [...])` display in editors
The actual bug was in `_item_to_dict`, not in the byte conversion pipeline.
`item.getRequest()` and `item.getResponse()` return `array.array` on Windows
Jython. Calling `bytes(array.array)` in Jython 2.7 calls `str()` on it,
producing the literal text `"array('b', [80, 79, ...])"` which was then
base64-encoded and stored. Every viewer was displaying the repr of the array
rather than actual HTTP bytes.

**Fix:** New `_raw_to_b64()` static method detects `array.array` and calls
`.tostring()` to extract raw bytes before encoding. New `_raw_bytes_to_str()`
normalises all byte types (str, bytes, bytearray, array.array) at every
boundary in the pipeline.

### Added
- `_raw_bytes_to_str()` — single source of truth for byte normalisation
- `_raw_to_b64()` — safe base64 encoder that handles all Jython byte types
- Diagnostic preview: logs first 80 bytes of request after `setMessage` so
  it is immediately obvious from the Diagnostics tab whether real HTTP or
  repr text is being stored
- Fixed second instance of the same bug in `_do_refresh_proxy` inline dict

---

## [5.7.0] — 2026-05-27

### Fixed
- `_py_to_java_bytes` rewritten to use `Java String.getBytes(ISO-8859-1)`
  which guarantees a true Java `byte[]` on all Jython versions and OSes,
  unlike `ByteArrayOutputStream.toByteArray()` which returns `array.array`
  on Windows Jython

### Changed
- Settings tab completely rewritten: scrollable, accurate step-by-step usage
  guide, "Where Loaded Data Appears" two-column layout, no stale text
- Removed all references to old "Save Project" / "Save All Activity" naming

---

## [5.6.0] — 2026-05-26

### Fixed
- `_FastWriter` class header (`class _FastWriter(object):`) was missing,
  making save operations fail with "object is not callable"
- Table columns reduced from 14 to 10 — dropped Edited, Cookies, IP, Title
  which were never populated
- Table switched to `AUTO_RESIZE_SUBSEQUENT_COLUMNS` so it fills panel width

---

## [5.5.0] — 2026-05-26

### Fixed
- Filter bar emoji (`\uD83D\uDD0D`) caused garbage rendering on Windows Jython
  — replaced with plain ASCII `"Filter:"`
- Filter was broken because `_vis` (displayed subset list) did not exist —
  `_select()` was indexing the wrong list when filter was active
- Request/Response editors were wrapped in `JTabbedPane` which broke Burp's
  native editor component layout — now plugged directly into `JSplitPane`

### Changed
- Bottom bar simplified: removed "Save Project" (redundant), renamed
  "Save All Activity" → "Export Session", "Load Project" → "Load Session",
  "Refresh Proxy Preview" → "Refresh"
- Checkboxes hidden (always all-ticked internally)
- `_vis` list introduced: always mirrors exactly what is in the JTable model

---

## [5.4.0] — 2026-05-26

### Added
- `_Inspector` panel (right-side, later removed as premature)
- Extended columns: Params, Edited, MIME type, Extension, Cookies, IP, Title
- Live filter bar with DocumentListener
- `_ReadOnlyTableModel` — cells no longer accidentally editable

### Changed
- `_Viewer` layout: horizontal request/response split (side-by-side)
- `_vis` tracking for filter-aware row selection

---

## [5.3.0] — 2026-05-25

### Changed
- UI restyled to match Burp's native HTTP history tab
- Columns reordered to match Burp: #, Host, Method, URL, Status, Length, Tool, Time
- Bottom bar: simplified button layout

---

## [5.0.0] — Initial public version

### Fixed
- Double-row bug: items list and table model always updated together in one
  place only. Never split across `add_item` and `add_items_batch`.
- Raw bytes bug: Burp message editor requires genuine Java `byte[]`
- Single-pixel row height (16px), no alternating colour, font matching Burp's
  native Proxy History tab

### Features
- Proxy History viewer with Burp native message editors
- Activity Store: auto-captures all traffic in real time
- Repeater Store: bookmark requests across sessions
- Export Session / Load Session (gzip NDJSON `.bsave` format)
- Auto-save on N captured requests
- Settings tab
- Diagnostics tab with byte conversion log and self-test
- Target sitemap restore on load
- Context menu: Save to Repeater Store
