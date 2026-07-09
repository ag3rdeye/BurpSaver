# Contributing to BurpSaver

Thank you for considering a contribution. Here is everything you need to know.

---

## Environment Setup

You cannot run BurpSaver outside Burp - it is a Burp extension, not a standalone script. To test changes you need:

1. Burp Suite Community Edition
2. Jython standalone JAR 2.7.3+
3. A text editor (the file is a single `.py`)

**Reload workflow:**
```
Edit BurpSaver.py
→ Burp: Extensions → Installed → select BurpSaver → Remove
→ Extensions → Add → Python → select BurpSaver.py
→ Check Diagnostics tab for errors
```

---

## Jython 2.7 Constraints - Read This First

BurpSaver runs on **Jython 2.7, not CPython**. Several things behave differently:

### Byte handling (most common source of bugs)

`item.getRequest()` and `item.getResponse()` return `array.array` on Windows Jython. **Do not call `bytes()` on this.** Use `_raw_bytes_to_str()` or `_raw_to_b64()` which are the single source of truth for byte conversion.

```python
# WRONG - bytes(array.array) calls str() → repr text
base64.b64encode(bytes(item.getRequest()))

# CORRECT
BurpExtender._raw_to_b64(item.getRequest())
```

### UI thread

All Swing UI updates must run on the Event Dispatch Thread:

```python
# WRONG - calling from background thread
self._model.addRow(row)

# CORRECT
SwingUtilities.invokeLater(lambda: self._model.addRow(row))
```

### No emoji in JLabel

```python
# WRONG - renders as raw escape sequences on Windows Jython
JLabel("\uD83D\uDD0D Filter:")

# CORRECT
JLabel("Filter:")
```

### No jarray import

```python
# WRONG - 'array' stdlib shadows jarray in Jython
import jarray

# CORRECT - use _py_to_java_bytes() which uses Java String.getBytes(ISO-8859-1)
```

### `unichr` not `chr`

```python
# Jython 2.7 uses unichr() for Unicode code points
unichr(ord(c) & 0xFF)   # correct
chr(ord(c) & 0xFF)      # also works but be consistent
```

---

## Code Style

- Single file (`BurpSaver.py`) - keep it that way. Burp loads one file.
- Classes prefixed with `_` are internal
- All public-facing strings in plain ASCII (no emoji, no non-ASCII)
- Log liberally with `_log()` - the Diagnostics tab is the debugger
- Every byte boundary must use `_raw_bytes_to_str()` or `_raw_to_b64()`

---

## What Makes a Good PR

- **Bug fix with a reproduction case** - describe what input triggers the bug
- **Diagnostics improvement** - more logging is almost always helpful
- **Performance** - batch UI updates, don't call `invokeLater` in a tight loop
- **New export format** - CSV, HAR, etc. would be useful

## What to Avoid

- Breaking the single-file structure
- Adding Python 3 syntax (must stay Jython 2.7 compatible)
- Dependencies that require pip install (nothing outside stdlib + Java APIs)
- UI redesigns without discussion first

---

## Filing Issues

Use the bug report template. The most useful thing you can include is the full **Diagnostics tab** output - it shows exactly what the byte conversion pipeline is doing and where it fails.
