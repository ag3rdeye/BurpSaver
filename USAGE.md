# BurpSaver — Usage Guide

## Table of Contents

1. [First-Time Setup](#1-first-time-setup)
2. [Understanding the Interface](#2-understanding-the-interface)
3. [Capturing Traffic](#3-capturing-traffic)
4. [Viewing and Filtering History](#4-viewing-and-filtering-history)
5. [Saving Your Session](#5-saving-your-session)
6. [Restoring a Session](#6-restoring-a-session)
7. [Auto-Save](#7-auto-save)
8. [Repeater Store](#8-repeater-store)
9. [Using the Diagnostics Tab](#9-using-the-diagnostics-tab)
10. [Typical Security Research Workflow](#10-typical-security-research-workflow)

---

## 1. First-Time Setup

### Step 1: Get Jython

BurpSaver runs on Jython 2.7 inside Burp. You need the **standalone JAR** (not the installer).

Download from: https://www.jython.org/download  
File to get: `jython-standalone-2.7.3.jar` (or latest 2.7.x)

### Step 2: Tell Burp about Jython

```
Burp → Extensions → Extension settings → Python Environment
                                          ↓
                                    Select file → jython-standalone-2.7.3.jar
```

> On older Burp versions this is at: **Extender → Options → Python Environment**

### Step 3: Load the Extension

```
Burp → Extensions → Installed → Add
    Extension type : Python
    Select file    : BurpSaver.py
    → Next
```

You should see a new **BurpSaver** tab appear in Burp's main tab bar with sub-tabs:
`Proxy History | Repeater Store | Activity Store | Settings | Diagnostics`

---

## 2. Understanding the Interface

### Tab Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Proxy History (N)  │  Repeater Store (N)  │  Activity Store (N) │  Settings  │  Diagnostics  │
├─────────────────────────────────────────────────────────────────┤
│  Filter: [_______________]  Clear   N entries                   │
├─────────────────────────────────────────────────────────────────┤
│  #  │ Host  │ Method │ URL  │ Params │ Status │ Length │ MIME … │
│─────────────────────────────────────────────────────────────────│
│  1  │ ...   │  GET   │ ...  │   3    │  200   │  1053  │ HTML  │
│  2  │ ...   │  POST  │ ...  │   12   │  204   │   694  │ HTML  │
│  …                                                              │
├──────────────────────────────┬──────────────────────────────────┤
│  Request                     │  Response                        │
│  Pretty  Raw  Hex            │  Pretty  Raw  Hex  Render        │
│                              │                                  │
│  GET /path HTTP/1.1          │  HTTP/1.1 200 OK                │
│  Host: example.com           │  Content-Type: text/html        │
│  …                           │  …                               │
├─────────────────────────────────────────────────────────────────┤
│  [Export Session]  [Load Session]  [Refresh]   Proxy: N entries │
└─────────────────────────────────────────────────────────────────┘
```

### Bottom Bar Buttons

| Button | What It Does |
|---|---|
| **Export Session** | Save everything to a `.bsave` file right now |
| **Load Session** | Pick a `.bsave` file and restore it |
| **Refresh** | Pull Burp's current live proxy history into the viewer |

### Column Reference

| Column | Meaning |
|---|---|
| # | Row number |
| Host | Target hostname |
| Method | HTTP method (GET, POST, OPTIONS…) |
| URL | Full URL |
| Params | Number of parameters detected |
| Status | HTTP response status code |
| Length | Response size in bytes |
| MIME type | Detected content type (HTML, JSON, script…) |
| Extension | File extension from the URL path |
| Time | Timestamp when captured |

---

## 3. Capturing Traffic

BurpSaver captures traffic **automatically** — no configuration needed.

Every request passing through Burp's proxy is stored in the **Activity Store** tab as it happens. You can see the count update in the tab title: `Activity Store (247)`.

The **Proxy History** tab shows Burp's own proxy history. Click **Refresh** to sync it into BurpSaver's viewer at any time.

> **Tip:** The Activity Store catches everything, including traffic you might have missed in Burp's own proxy history. It's your safety net.

---

## 4. Viewing and Filtering History

### Clicking a Row

Click any row in the table to load its full request and response into the editors below. The editors are Burp's native message editors — you get Pretty, Raw, Hex, and (for responses) Render views exactly like Burp's own proxy history.

### Using the Filter

Type any text into the **Filter** box — the table instantly narrows to rows that match in any column (host, URL, method, status, MIME type, etc.).

Examples:

| You type | Result |
|---|---|
| `google.com` | Only rows with `google.com` in the host or URL |
| `POST` | Only POST requests |
| `200` | Only 200-status responses |
| `json` | Only JSON responses |
| `admin` | Any row mentioning "admin" anywhere |

Click **Clear** to remove the filter and show all rows.

### Column Sorting

Click any column header to sort by that column. Click again to reverse. Useful for finding the largest responses, the most recent requests, or all requests from a specific host.

---

## 5. Saving Your Session

When you are done for the day (or at any point):

1. Click **Export Session** in the bottom bar
2. Choose a folder and filename in the file dialog
3. BurpSaver adds `.bsave` automatically if you don't type it

The export includes:
- Everything in **Proxy History**
- Everything in **Repeater Store**
- Everything in **Activity Store**
- All sitemap entries

The file is compressed (gzip + NDJSON) so it is efficient even for large sessions.

> **Recommendation:** Save to a folder organised by engagement:
> ```
> pentests/
> ├── target-corp-2026-05-26/
> │   ├── session-morning.bsave
> │   └── session-afternoon.bsave
> ```

---

## 6. Restoring a Session

On your next Burp session:

1. Load BurpSaver (or it loads automatically if already installed)
2. Click **Load Session**
3. Pick your `.bsave` file
4. Wait for the progress bar to complete

After loading, check each location:

| What was saved | Where it appears after load |
|---|---|
| Proxy History | BurpSaver **Proxy History** tab + Burp's **Target → Site map** |
| Repeater Store | Burp's native **Repeater** tab (check there — new tabs are added) |
| Activity Store | BurpSaver **Activity Store** tab |
| Sitemap | Burp **Target → Site map** |

> **Note:** After loading, click **Refresh** on the Proxy History tab if the count shows 0 — the first load may require a refresh to display.

---

## 7. Auto-Save

Auto-save protects you if Burp crashes or you forget to export.

**Setup:**

1. Go to the **Settings** tab
2. Set "Auto-save every N captured requests" — e.g. `100`
3. Click **Browse** and choose a destination file
4. Click **Apply**

BurpSaver will automatically export every time 100 new requests are captured. The file is overwritten each time (not appended), so it always reflects your latest state.

**Recommended setting for an active engagement:** `50` requests

---

## 8. Repeater Store

The Repeater Store lets you bookmark specific requests to revisit across sessions.

**Saving to Repeater Store:**

Right-click any row in the Proxy History or Activity Store → **Save to Repeater Store**

**Viewing saved requests:**

Click the **Repeater Store** tab. The count in the tab title shows how many you have saved.

**After loading a session:**

Saved repeater requests are sent directly to Burp's native Repeater tab — you'll see new tabs appear there with your saved requests ready to replay.

---

## 9. Using the Diagnostics Tab

The **Diagnostics** tab shows an internal log of what BurpSaver is doing. Use it to troubleshoot problems.

**What to look for:**

| Log line | What it means |
|---|---|
| `_item_to_dict: req type=array req len=4540` | Traffic captured successfully |
| `_py_to_java_bytes: in_len=4540 out_type=array out_len=4540` | Byte conversion working |
| `setMessage OK (via invokeLater)` | Editor loaded successfully |
| `req preview: 'GET /path HTTP/1.1\r\n...'` | Confirms real HTTP, not garbage |
| `ERROR:` | Something went wrong — copy this and file an issue |

**Buttons in Diagnostics:**

| Button | Action |
|---|---|
| Refresh Log | Update the log display |
| Clear Log | Wipe the log |
| Run Byte Test | Run a self-test of the byte conversion pipeline |

---

## 10. Typical Security Research Workflow

### Day 1 — Starting an Engagement

```
1. Open Burp Suite Community
2. BurpSaver loads automatically (already installed)
3. Configure your browser to proxy through Burp (127.0.0.1:8080)
4. Browse the target application normally
5. BurpSaver captures everything in Activity Store automatically
6. Interesting endpoint? Right-click → Save to Repeater Store
7. End of day: click Export Session → save as target-day1.bsave
8. Close Burp
```

### Day 2 — Continuing

```
1. Open Burp Suite Community
2. BurpSaver loads
3. Click Load Session → pick target-day1.bsave
4. All history is back. Repeater tabs restored.
5. Continue where you left off
6. End of day: Export Session → target-day2.bsave
```

### Mid-Session Backup

```
Every hour or so: Export Session → overwrite yesterday's file
OR configure Auto-Save to do this automatically
```

### Reviewing Traffic

```
1. Click Proxy History tab → Refresh
2. Filter: type the endpoint you are testing (e.g. "/api/v2/user")
3. Click each row → review request/response in editors
4. Spotted something interesting? Right-click → Save to Repeater Store
```

---

## Tips for Large Sessions

- Use the **Filter** to narrow down before scrolling — the filter is instant even with thousands of rows
- Export frequently — a 10,000 request session file is typically 5–15 MB compressed
- If load is slow, it's normal — Burp's sitemap restore is the slowest part
- The Activity Store tab is your most complete record — Proxy History only shows what Burp's own filter lets through

---

## Keyboard Shortcuts

BurpSaver inherits Burp's standard keyboard behaviour in the editors:

| Action | Shortcut |
|---|---|
| Search in editor | `Ctrl+F` |
| Copy selected text | `Ctrl+C` |
| Select all | `Ctrl+A` |

---

*BurpSaver v5.8.0 — Created by Thirdeye*
