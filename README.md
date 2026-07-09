# BurpSaver

**Full session save and restore for Burp Suite Community Edition.**

Burp Suite Community Edition does not persist your session between restarts — when you close Burp, your entire Proxy History, Repeater tabs, and captured traffic are gone. BurpSaver solves this by letting you export your full session to a `.bsave` file and restore it exactly as you left it the next time you open Burp.

![Python](https://img.shields.io/badge/python-2.7%20%28Jython%29-blue)
![Burp Suite](https://img.shields.io/badge/Burp%20Suite-Community%20Edition-orange)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Version](https://img.shields.io/badge/version-5.8.0-green)

---

## What It Does

| Feature | Details |
|---|---|
| **Proxy History viewer** | Browse all captured traffic with filter, side-by-side request/response editors |
| **Export Session** | Save Proxy History + Repeater Store + Activity Store to a single `.bsave` file |
| **Load Session** | Restore a previous session — history, repeater tabs, sitemap all come back |
| **Activity Store** | Auto-captures every request passing through Burp's proxy in real time |
| **Repeater Store** | Save interesting requests to revisit across sessions |
| **Auto-save** | Configurable auto-export every N captured requests |
| **Live filter** | Instant case-insensitive filter across all table columns |

---

## Why `.bsave` and Not `.burp`?

Burp Pro's `.burp` format is a proprietary binary (Java serialized) format that Portswigger has not documented. BurpSaver uses **gzip-compressed NDJSON** instead — meaning your session files are:

- Readable outside Burp (`gunzip session.bsave | python -m json.tool`)
- Portable across Burp versions
- Inspectable and scriptable without any Burp dependency
- Safe from breakage if Burp's internal format ever changes

---

## Screenshots

> _Proxy History tab with live filter and side-by-side request/response editors_

> _Settings tab with auto-save configuration_

---

## Requirements

| Requirement | Version |
|---|---|
| Burp Suite Community Edition | Any recent version |
| Jython Standalone JAR | 2.7.3 or later |
| Java | 8 or later |
| Operating System | Windows, macOS, Linux |

Python 3 is **not** supported — Burp's extension API requires Jython 2.7.

---

## Installation

### 1. Download Jython Standalone

Download the Jython standalone JAR from [jython.org](https://www.jython.org/download):

```
jython-standalone-2.7.3.jar
```

### 2. Configure Jython in Burp

1. Open Burp Suite
2. Go to **Extensions → Extension settings** (or **Extender → Options** in older versions)
3. Under **Python Environment**, click **Select file**
4. Choose the `jython-standalone-2.7.3.jar` you downloaded

### 3. Load BurpSaver

1. Go to **Extensions → Installed** (or **Extender → Extensions**)
2. Click **Add**
3. Set **Extension type** to `Python`
4. Click **Select file** and choose `BurpSaver.py`
5. Click **Next** — you should see `BurpSaver` appear as a new tab in Burp

---

## Usage

### Capturing Traffic

BurpSaver captures all traffic automatically as soon as it loads. Every request passing through the Burp proxy is recorded in the **Activity Store** tab in real time. No configuration needed.

### Viewing Proxy History

Click the **Proxy History** tab inside BurpSaver. Click **Refresh** to pull the current Burp proxy history into the viewer. Click any row to see the full request and response side by side.

Use the **Filter** bar to narrow down by host, method, URL, status code, or MIME type.

### Exporting a Session

When you are ready to close Burp, click **Export Session**. Choose a location and filename — the file will be saved with the `.bsave` extension. This saves everything: proxy history, repeater store, activity store, and target sitemap entries.

### Loading a Session

On your next Burp session, load BurpSaver and click **Load Session**. Pick your `.bsave` file. Everything is restored:

- Proxy history appears in the **Proxy History** tab
- Repeater requests are sent to Burp's native **Repeater** tab
- Activity appears in the **Activity Store** tab
- Sitemap entries are added to Burp's **Target → Site map**

### Auto-Save

Go to the **Settings** tab to configure auto-save. Set a number of captured requests (e.g. `50`) and choose a destination file. BurpSaver will automatically export every time that many new requests are captured, so you never lose progress.

---

## File Format

`.bsave` files are gzip-compressed NDJSON (one JSON object per line). Each line has the structure:

```json
{"s": "section", "d": { ...data dict... }}
```

Sections: `meta`, `proxy`, `repeater`, `activity`, `sitemap`

To inspect a session file outside Burp:

```bash
# On Linux / macOS
gunzip -c mysession.bsave | head -5

# On Windows (PowerShell)
# Rename to .gz and open with 7-Zip, or use Python:
python -c "
import gzip, json
with gzip.open('mysession.bsave', 'rt') as f:
    for line in f:
        print(json.loads(line)['s'])
"
```

---

## Project Structure

```
burpsaver/
├── BurpSaver.py          # The extension — single file, load directly into Burp
├── README.md             # This file
├── USAGE.md              # Step-by-step usage guide with screenshots
├── CHANGELOG.md          # Version history
├── requirements.txt      # External dependencies (Jython JAR)
└── .github/
    └── ISSUE_TEMPLATE.md # Bug report template
```

---

## Known Limitations

- **Burp Community only target** — Burp Pro users can use BurpSaver but Pro's native save is more integrated
- **No WebSocket history** — WebSocket frames are not currently captured
- **Large sessions** — sessions with tens of thousands of requests may take a few seconds to load
- **Jython 2.7 only** — Python 3 is not supported by Burp's extension API

---

## Troubleshooting

**Editors show `array('b', [72, 84, ...])` instead of HTTP text**
This was a Windows Jython bug fixed in v5.8.0. Make sure you are using the latest version.

**Extension loads but no tab appears**
Check that Jython is correctly configured under Extension settings. The Burp error log (Extensions → Installed → select BurpSaver → Errors) will show the exact error.

**Load Session does nothing**
Ensure the `.bsave` file was created by BurpSaver v5.0 or later. Files from earlier versions used a different format and are not compatible.

**Filter doesn't update the table**
This was fixed in v5.5.0. Update to the latest version.

---

## Contributing

Issues and pull requests are welcome. When filing a bug, please include:

1. Your OS and Java version (`java -version`)
2. Your Jython JAR version
3. The content of the **Diagnostics** tab in BurpSaver
4. Steps to reproduce

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Author

Created by **Thirdeye**
