# -*- coding: utf-8 -*-
# =============================================================================
#  BurpSaver.py  v5.5.0
#  Burp Suite Community Edition - Full Session Save / Load Extension
#
#  Language : Python 2.7  (Jython 2.7 inside Burp)
#  Requires : Jython standalone JAR configured in Extender -> Options
#
#  Created by Thirdeye
#
#  FIXES in v5.0
#  - DOUBLE ROW BUG: items list and table model are always updated together
#    in one place only (_append_to_viewer). Never split across add_item and
#    add_items_batch to avoid the off-by-one duplication.
#  - RAW BYTES BUG: Burp message editor requires a genuine Java byte[].
#    We now use Jython's built-in array module with typecode 'b' AND sign-
#    correct conversion. Also, the viewer's IMessageEditorController methods
#    return the stored raw Python bytes re-converted every call.
#  - UI: single-pixel row height (16px), no alternating colour, identical
#    font/grid to Burp's native Proxy History tab.
#  - "Created by Thirdeye" plain text, no badge, bottom-right corner.
#  - "Export Session" saves all history + repeater + activity in one click.
#  - "Load Session" restores a previously exported session file.
# =============================================================================

import base64
import datetime
import threading
import traceback as _tb
import json
# jarray removed - using pure Java byte[] construction instead

from java.io import (File, FileOutputStream, FileInputStream,
                     OutputStreamWriter, InputStreamReader,
                     BufferedWriter, BufferedReader,
                     ByteArrayOutputStream)
from java.util.zip import GZIPOutputStream, GZIPInputStream
from java.nio.charset import Charset
from java.lang import String as _JString

from burp import (IBurpExtender, ITab, IExtensionStateListener,
                  IContextMenuFactory, IHttpRequestResponse,
                  IHttpListener, IMessageEditorController)

from javax.swing import (
    JPanel, JButton, JLabel, JFileChooser, JScrollPane,
    JTable, JTabbedPane, JOptionPane, SwingUtilities,
    BorderFactory, JProgressBar, JCheckBox, JTextField,
    JMenuItem, JSplitPane, ListSelectionModel)
from javax.swing.table import DefaultTableModel
from javax.swing.filechooser import FileNameExtensionFilter
from javax.swing.event import ListSelectionListener
from java.awt import (BorderLayout, FlowLayout, Color, Font, Dimension, Insets)
from java.util import ArrayList

VERSION  = "5.8.0"
EXT_NAME = "BurpSaver"
FILE_EXT = "bsave"
CREATOR  = "Created by Thirdeye"

TOOL_NAMES = {
    1:  "Suite",    2:  "Target",   4:   "Proxy",    8:   "Spider",
    16: "Scanner",  32: "Intruder", 64:  "Repeater", 128: "Sequencer",
    256:"Decoder",  512:"Comparer", 1024:"Extender",
}

UTF8    = Charset.forName("UTF-8")

# =============================================================================
#  Global diagnostics log  (thread-safe ring buffer, max 500 lines)
# =============================================================================
import threading as _threading
_LOG_LOCK  = _threading.Lock()
_LOG_LINES = []
_LOG_MAX   = 500

def _log(msg):
    ts  = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = "[{}] {}".format(ts, msg)
    with _LOG_LOCK:
        _LOG_LINES.append(line)
        if len(_LOG_LINES) > _LOG_MAX:
            del _LOG_LINES[0]

def _get_logs():
    with _LOG_LOCK:
        return list(_LOG_LINES)
C_GREEN  = Color(0x27AE60)
C_RED    = Color(0xC0392B)
C_BLUE   = Color(0x2980B9)
C_PURPLE = Color(0x8E44AD)
C_DARK   = Color(0x2C3E50)
C_ORANGE = Color(0xE67E22)


# =============================================================================
#  Convert Python bytes -> Java byte[]
#  ByteArrayOutputStream.toByteArray() produces a real Java byte[].
#  This bypasses jarray entirely (jarray was shadowed by Python stdlib).
# =============================================================================
# ISO-8859-1 charset - used for lossless byte<->char mapping
_ISO = Charset.forName("ISO-8859-1")

def _raw_bytes_to_str(data):
    """Convert ANY Jython/Java byte sequence to a raw Python str (iso-8859-1).
    This is the single source of truth for byte normalisation in this extension.

    Type map (Windows Jython on Java 11):
      array.array  <- getRequest()/getResponse() return this
      str          <- base64.b64decode() returns this in Jython 2.7
      bytearray    <- explicit bytearray() construction
      bytes        <- alias for str in Jython 2.7
    """
    if data is None:
        return ""
    t = type(data).__name__
    if t == "array":
        return data.tostring()          # raw bytes, fastest path
    if isinstance(data, str):
        return data                     # already raw in Jython 2.7
    if isinstance(data, bytearray):
        return data.decode("iso-8859-1")
    # Fallback: iterate treating each element as unsigned byte
    return bytearray(int(b) & 0xFF for b in data).decode("iso-8859-1")


def _py_to_java_bytes(data, log=None):
    """Convert Python str/bytes/bytearray/array.array -> genuine Java byte[] ([B).

    Uses Java String.getBytes(ISO-8859-1) which ALWAYS returns a true [B,
    unlike ByteArrayOutputStream.toByteArray() which returns array.array on
    Windows Jython, causing Burp editors to render repr() instead of HTTP.
    """
    try:
        raw = _raw_bytes_to_str(data)    # normalise to Python str
        if not raw:
            if log: log("_py_to_java_bytes: empty -> empty byte[]")
            return _JString("").getBytes(_ISO)

        # ISO-8859-1 is lossless: every byte value 0-255 maps to exactly one char
        uni    = u"".join(unichr(ord(c) & 0xFF) for c in raw)
        result = _JString(uni).getBytes(_ISO)   # guaranteed real Java byte[]

        if log:
            try:    cls = result.getClass().getName()
            except: cls = type(result).__name__
            log("_py_to_java_bytes: in_len={} out_type={} out_len={}".format(
                len(raw), cls, len(result)))
        return result

    except Exception:
        import traceback as _tbx
        if log: log("_py_to_java_bytes ERROR:\n" + _tbx.format_exc())
        return _JString("").getBytes(_ISO)



# =============================================================================
#  NDJSON / GZIP writer
# =============================================================================
class _FastWriter(object):
    def __init__(self, path):
        fos = FileOutputStream(File(path))
        gos = GZIPOutputStream(fos)
        osw = OutputStreamWriter(gos, UTF8)
        self._bw = BufferedWriter(osw, 131072)

    def _write(self, s, d):
        self._bw.write(json.dumps({"s": s, "d": d}, separators=(",", ":")))
        self._bw.newLine()

    def write_meta(self, d):     self._write("meta",     d)
    def write_proxy(self, d):    self._write("proxy",    d)
    def write_repeater(self, d): self._write("repeater", d)
    def write_activity(self, d): self._write("activity", d)
    def write_sitemap(self, d):  self._write("sitemap",  d)

    def close(self):
        self._bw.flush()
        self._bw.close()


# =============================================================================
#  NDJSON reader  (callback-based, no iterator, no deadlock)
# =============================================================================
def _read_ndjson(path, cb):
    fis = FileInputStream(File(path))
    gis = GZIPInputStream(fis, 131072)
    isr = InputStreamReader(gis, UTF8)
    br  = BufferedReader(isr, 131072)
    try:
        while True:
            line = br.readLine()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                cb(obj.get("s", ""), obj.get("d", {}))
            except Exception:
                pass
    finally:
        try:
            br.close()
        except Exception:
            pass


# =============================================================================
#  Stored HTTP entry  (plain Python object, NOT IHttpRequestResponse)
#  We keep raw bytes in Python and only convert to Java byte[] on demand.
# =============================================================================
class _Entry(object):
    __slots__ = ("_req", "_resp", "_meta")

    def __init__(self, d):
        # b64decode in Jython 2.7 returns str (raw bytes) - normalise for safety
        self._req  = _raw_bytes_to_str(base64.b64decode(d["request"]))  if d.get("request")  else ""
        self._resp = _raw_bytes_to_str(base64.b64decode(d["response"])) if d.get("response") else ""
        self._meta = d   # original dict kept for sitemap/repeater restore

    def req_bytes(self):
        return _py_to_java_bytes(self._req)

    def resp_bytes(self):
        return _py_to_java_bytes(self._resp)


# =============================================================================
#  Thin IHttpRequestResponse wrapper used ONLY for addToSiteMap
# =============================================================================
class _SitemapItem(IHttpRequestResponse):
    def __init__(self, svc, req_raw, resp_raw, comment="", highlight=""):
        self._svc  = svc
        # req_raw/resp_raw come from base64.b64decode -> normalise then convert
        self._req  = _py_to_java_bytes(_raw_bytes_to_str(req_raw))
        self._resp = _py_to_java_bytes(_raw_bytes_to_str(resp_raw)) if resp_raw else _py_to_java_bytes("")
        self._com  = comment
        self._hi   = highlight

    def getHttpService(self):    return self._svc
    def getRequest(self):        return self._req
    def getResponse(self):       return self._resp
    def getComment(self):        return self._com
    def getHighlight(self):      return self._hi
    def setHttpService(self, v): self._svc = v
    def setRequest(self, v):     self._req = v
    def setResponse(self, v):    self._resp = v
    def setComment(self, v):     self._com = v
    def setHighlight(self, v):   self._hi = v


# =============================================================================
#  Row selection listener
# =============================================================================
class _RowSel(ListSelectionListener):
    def __init__(self, viewer):
        self._v = viewer

    def valueChanged(self, e):
        if not e.getValueIsAdjusting():
            row = self._v._table.getSelectedRow()
            if row >= 0:
                self._v._select(row)


# =============================================================================
#  Read-only table model (cells not editable)
# =============================================================================
class _ReadOnlyTableModel(DefaultTableModel):
    def __init__(self, cols):
        DefaultTableModel.__init__(self, cols, 0)

    def isCellEditable(self, row, col):
        return False





# =============================================================================
#  History viewer panel  (matches Burp's HTTP history layout)
#  Layout:
#    NORTH  : filter bar
#    CENTER : vertical split
#               TOP  : table (scrollable)
#               BOT  : horizontal split
#                        LEFT  : tabbed req / resp editors
#                        RIGHT : Inspector panel
#  Strict invariant: len(self._entries) == self._model.getRowCount() ALWAYS
# =============================================================================
class _Viewer(IMessageEditorController):

    # Practical columns for a security researcher
    COLS   = ["#", "Host", "Method", "URL", "Params",
              "Status", "Length", "MIME type", "Extension", "Time"]
    WIDTHS = [35,  155,    58,      310,    52,
              55,  65,     80,      70,     140]

    def __init__(self, callbacks, helpers):
        self._callbacks = callbacks
        self._helpers   = helpers
        self._entries     = []    # master list of (_Entry, row_list)
        self._vis         = []    # currently displayed subset (mirrors model)
        self._sel         = [None]  # currently selected _Entry
        self._filter_text = [""]  # active filter string (lowercase)
        self._panel       = JPanel(BorderLayout())
        self._build()

    # ---------------------------------------------------------------- build
    def _build(self):
        from javax.swing import JTextField as _JTF, JLabel as _JLbl
        from javax.swing.event import DocumentListener as _DL

        # ---- Filter bar ----
        # Plain ASCII label - Jython 2.7 encodes source as UTF-8 but
        # Swing JLabel in some JVMs mis-renders non-BMP emoji; keep it safe.
        filter_bar = JPanel(FlowLayout(FlowLayout.LEFT, 6, 2))
        filter_bar.setBackground(Color(0xEDEDED))
        filter_bar.setBorder(BorderFactory.createMatteBorder(0, 0, 1, 0, Color(0xCCCCCC)))

        fi = _JLbl("Filter:")
        fi.setFont(Font("Dialog", Font.BOLD, 11))
        fi.setForeground(Color(0x444444))
        filter_bar.add(fi)

        self._filter_fld = _JTF(28)
        self._filter_fld.setFont(Font("Dialog", Font.PLAIN, 12))
        self._filter_fld.setToolTipText("Filter by host, method, URL, status, MIME type (case-insensitive)")

        viewer_ref = [self]
        class _FilterDoc(_DL):
            def insertUpdate(self, e):  viewer_ref[0]._apply_filter()
            def removeUpdate(self, e):  viewer_ref[0]._apply_filter()
            def changedUpdate(self, e): viewer_ref[0]._apply_filter()
        self._filter_fld.getDocument().addDocumentListener(_FilterDoc())
        filter_bar.add(self._filter_fld)

        clr_f = JButton("Clear")
        clr_f.setFont(Font("Dialog", Font.PLAIN, 11))
        clr_f.setFocusPainted(False)
        clr_f.setMargin(Insets(1, 6, 1, 6))
        clr_f.setToolTipText("Clear filter")
        clr_f.addActionListener(lambda e: self._clear_filter())
        filter_bar.add(clr_f)

        self._count_lbl = _JLbl("0 entries")
        self._count_lbl.setFont(Font("Dialog", Font.ITALIC, 11))
        self._count_lbl.setForeground(Color(0x666666))
        filter_bar.add(self._count_lbl)

        # ---- Table ----
        self._model = _ReadOnlyTableModel(self.COLS)
        self._table = JTable(self._model)
        self._table.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)
        self._table.setAutoResizeMode(JTable.AUTO_RESIZE_SUBSEQUENT_COLUMNS)
        self._table.setShowGrid(True)
        self._table.setGridColor(Color(0xE5E5E5))
        self._table.setIntercellSpacing(Dimension(1, 0))
        self._table.setRowHeight(18)
        self._table.setFont(Font("Dialog", Font.PLAIN, 12))
        self._table.setSelectionBackground(Color(0xC5D8F8))
        self._table.setSelectionForeground(Color.BLACK)
        self._table.setBackground(Color.WHITE)

        th = self._table.getTableHeader()
        th.setFont(Font("Dialog", Font.PLAIN, 11))
        th.setBackground(Color(0xEBEBEB))
        th.setForeground(Color(0x222222))
        th.setReorderingAllowed(True)

        for i, w in enumerate(self.WIDTHS):
            self._table.getColumnModel().getColumn(i).setPreferredWidth(w)
        self._table.getSelectionModel().addListSelectionListener(_RowSel(self))

        table_scroll = JScrollPane(self._table)
        table_scroll.setBorder(None)

        # ---- Burp native editors (side-by-side, no wrapping tabs) ----
        self._req_ed  = self._callbacks.createMessageEditor(self, False)
        self._resp_ed = self._callbacks.createMessageEditor(self, False)

        # Side-by-side horizontal split: Request | Response
        editor_split = JSplitPane(JSplitPane.HORIZONTAL_SPLIT,
                                  self._req_ed.getComponent(),
                                  self._resp_ed.getComponent())
        editor_split.setResizeWeight(0.5)
        editor_split.setBorder(None)
        editor_split.setDividerSize(4)
        # Set 50/50 after layout
        SwingUtilities.invokeLater(lambda: editor_split.setDividerLocation(0.5))

        # Vertical main split: table (top) | editors (bottom)
        main_split = JSplitPane(JSplitPane.VERTICAL_SPLIT, table_scroll, editor_split)
        main_split.setDividerLocation(220)
        main_split.setResizeWeight(0.40)
        main_split.setBorder(None)
        main_split.setDividerSize(5)
        main_split.setOneTouchExpandable(True)

        self._panel.add(filter_bar, BorderLayout.NORTH)
        self._panel.add(main_split, BorderLayout.CENTER)

    # ---------------------------------------------------------------- public
    def panel(self):
        return self._panel

    def count(self):
        return len(self._entries)

    def _append(self, entry, row_data):
        """Append a single entry (used internally)."""
        t = (entry, row_data)
        self._entries.append(t)
        self._vis.append(t)
        self._model.addRow(row_data)
        n = self._model.getRowCount()
        SwingUtilities.invokeLater(
            lambda: self._count_lbl.setText("{} entr{}".format(n, "y" if n == 1 else "ies")))

    # ---------------------------------------------------------------- filter
    def _apply_filter(self):
        txt = self._filter_fld.getText().strip().lower()
        self._filter_text[0] = txt
        if txt:
            self._vis = [e for e in self._entries if self._matches(e, txt)]
        else:
            self._vis = list(self._entries)
        self._rebuild_model()

    def _matches(self, entry_tuple, txt):
        _, row = entry_tuple
        return any(txt in str(cell).lower() for cell in row)

    def _rebuild_model(self):
        vis = list(self._vis)   # snapshot for lambda
        def _do():
            self._model.setRowCount(0)
            for _, row in vis:
                self._model.addRow(row)
            n = self._model.getRowCount()
            self._count_lbl.setText("{} entr{}".format(n, "y" if n == 1 else "ies"))
        SwingUtilities.invokeLater(_do)

    def _clear_filter(self):
        self._filter_fld.setText("")

    # ---------------------------------------------------------------- selection
    def _select(self, view_row):
        """Called from _RowSel with the view (display) row index."""
        # When filter is active the model row count != len(self._entries).
        # We stored a parallel _vis list that mirrors the current model.
        if 0 <= view_row < len(self._vis):
            entry, _ = self._vis[view_row]
        else:
            return

        self._sel[0] = entry
        try:
            req_java  = _py_to_java_bytes(entry._req,  log=_log)
            resp_java = _py_to_java_bytes(entry._resp, log=_log)
            _log("_select row={} req_len={} resp_len={}".format(
                view_row, len(entry._req), len(entry._resp)))
            self._req_ed.setMessage(req_java,  True)
            self._resp_ed.setMessage(resp_java, False)
            # Log the first 80 bytes so we can verify it's real HTTP not repr()
            try:
                preview = entry._req[:80].replace("\r","\\r").replace("\n","\\n")
                _log("  setMessage OK (via invokeLater)")
                _log("  req preview: {}".format(repr(preview)))
            except Exception:
                _log("  setMessage OK (via invokeLater)")
        except Exception:
            _log("_select ERROR: " + _tb.format_exc())

    # ---------------------------------------------------------------- clear
    def clear(self):
        self._entries = []
        self._vis     = []
        self._sel[0]  = None
        empty = _py_to_java_bytes(b"")
        SwingUtilities.invokeLater(lambda: self._model.setRowCount(0))
        SwingUtilities.invokeLater(lambda: self._req_ed.setMessage(empty, True))
        SwingUtilities.invokeLater(lambda: self._resp_ed.setMessage(empty, False))
        SwingUtilities.invokeLater(lambda: self._count_lbl.setText("0 entries"))

    # ---------------------------------------------------------------- batch add
    def batch_add(self, pairs):
        """pairs = list of (_Entry, [row_data]).
        Appends to _entries and, when no filter is active, also to _vis/model.
        """
        txt = self._filter_text[0]
        new_vis = []
        for entry, row in pairs:
            t = (entry, row)
            self._entries.append(t)
            if not txt or self._matches(t, txt):
                new_vis.append(t)
        if not new_vis:
            return
        self._vis.extend(new_vis)
        rows = [r for _, r in new_vis]
        def _do(rs=rows):
            for r in rs:
                self._model.addRow(r)
            n = self._model.getRowCount()
            self._count_lbl.setText("{} entr{}".format(n, "y" if n == 1 else "ies"))
        SwingUtilities.invokeLater(_do)

    # ---------------------------------------------------------------- IMessageEditorController
    def getHttpService(self):
        return None   # no live service needed for viewing stored data

    def getRequest(self):
        s = self._sel[0]
        return s.req_bytes() if s else _py_to_java_bytes(b"")

    def getResponse(self):
        s = self._sel[0]
        return s.resp_bytes() if s else _py_to_java_bytes(b"")


# =============================================================================
#  Main extender
# =============================================================================
class BurpExtender(IBurpExtender, ITab, IExtensionStateListener, IHttpListener):

    def registerExtenderCallbacks(self, callbacks):
        self._callbacks = callbacks
        self._helpers   = callbacks.getHelpers()
        callbacks.setExtensionName("{} v{}".format(EXT_NAME, VERSION))
        callbacks.registerExtensionStateListener(self)
        callbacks.registerHttpListener(self)

        self._act_lock  = threading.Lock()
        self._act_store = []          # list of dicts (raw)
        self._rep_store = []          # list of dicts (raw)
        self._save_lock = threading.Lock()
        self._auto_path = [None]
        self._auto_n    = [0]

        SwingUtilities.invokeLater(lambda: self._build_ui())
        self._callbacks.printOutput("[{}] v{} loaded.".format(EXT_NAME, VERSION))

    def getTabCaption(self):  return EXT_NAME
    def getUiComponent(self): return self._panel

    # ------------------------------------------------------------------ capture
    def processHttpMessage(self, toolFlag, isRequest, msgInfo):
        if isRequest:
            return
        try:
            d = self._item_to_dict(msgInfo)
            if not d:
                return
            d["tool"]        = TOOL_NAMES.get(toolFlag, str(toolFlag))
            d["captured_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._act_lock:
                self._act_store.append(d)
                total = len(self._act_store)
            SwingUtilities.invokeLater(lambda t=total: self._set_act_count(t))
            _log("Captured tool={} method={} url={} req_b64_len={} resp_b64_len={}".format(
                d.get("tool","?"), d.get("method","?"), d.get("url","?"),
                len(d.get("request","")), len(d.get("response",""))))
            n = self._auto_n[0]
            p = self._auto_path[0]
            if p and n and total % n == 0:
                self._bg(self._do_save, p, True)
        except Exception as ex:
            self._callbacks.printError("Capture: " + str(ex))

    def _set_act_count(self, total):
        try:
            self._tabs.setTitleAt(2, "Activity Store ({})".format(total))
            self._act_lbl.setText("Live captured: {}".format(total))
        except Exception:
            pass

    def _bg(self, fn, *args):
        t = threading.Thread(target=fn, args=args)
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._proxy_v = _Viewer(self._callbacks, self._helpers)
        self._act_v   = _Viewer(self._callbacks, self._helpers)
        self._rep_v   = _Viewer(self._callbacks, self._helpers)

        self._panel = JPanel(BorderLayout(0, 0))

        self._tabs = JTabbedPane()
        self._tabs.setFont(Font("Dialog", Font.PLAIN, 12))
        self._tabs.addTab("Proxy History (0)",  self._proxy_tab())
        self._tabs.addTab("Repeater Store (0)", self._repeater_tab())
        self._tabs.addTab("Activity Store (0)", self._activity_tab())
        self._tabs.addTab("Settings",           self._settings_tab())
        self._tabs.addTab("Diagnostics",        self._diag_tab())
        self._panel.add(self._tabs, BorderLayout.CENTER)
        self._panel.add(self._south(), BorderLayout.SOUTH)

        self._callbacks.addSuiteTab(self)
        self._callbacks.registerContextMenuFactory(_CtxMenu(self))

    # ---- toolbar helper ----
    def _tbar(self, *widgets):
        bar = JPanel(FlowLayout(FlowLayout.LEFT, 6, 3))
        bar.setBackground(Color(0xF8F8F8))
        bar.setBorder(BorderFactory.createMatteBorder(0, 0, 1, 0, Color(0xDDDDDD)))
        for w in widgets:
            bar.add(w)
        return bar

    def _proxy_tab(self):
        info = JLabel("Imported Proxy History - select a row to inspect")
        info.setFont(Font("Dialog", Font.PLAIN, 11))
        info.setForeground(Color(0x666666))
        clr = self._sbtn("Clear", C_RED, lambda e: self._clear_proxy())
        pnl = JPanel(BorderLayout())
        pnl.add(self._tbar(info, clr), BorderLayout.NORTH)
        pnl.add(self._proxy_v.panel(), BorderLayout.CENTER)
        return pnl

    def _repeater_tab(self):
        info = JLabel(
            "Right-click any request -> 'BurpSaver: Add to Repeater Store'  "
            "|  Entries restore as real Repeater tabs on load.")
        info.setFont(Font("Dialog", Font.PLAIN, 11))
        info.setForeground(Color(0x666666))
        clr = self._sbtn("Clear", C_RED, lambda e: self._clear_rep())
        pnl = JPanel(BorderLayout())
        pnl.add(self._tbar(info, clr), BorderLayout.NORTH)
        pnl.add(self._rep_v.panel(), BorderLayout.CENTER)
        return pnl

    def _activity_tab(self):
        self._act_lbl = JLabel("Live captured: 0")
        self._act_lbl.setFont(Font("Dialog", Font.BOLD, 12))
        self._act_lbl.setForeground(C_BLUE)

        ref  = self._sbtn("Refresh View", C_BLUE,  lambda e: self._bg(self._do_refresh_act))
        snap = self._sbtn("Snapshot Proxy History", C_DARK, lambda e: self._bg(self._do_snap))
        clr  = self._sbtn("Clear", C_RED, lambda e: self._clear_act())

        pnl = JPanel(BorderLayout())
        pnl.add(self._tbar(self._act_lbl, ref, snap, clr), BorderLayout.NORTH)
        pnl.add(self._act_v.panel(), BorderLayout.CENTER)
        return pnl

    def _settings_tab(self):
        from javax.swing import Box, JScrollPane as _JSP, JTextArea as _JTA
        from java.awt import GridBagLayout, GridBagConstraints as GBC

        outer = JPanel(BorderLayout())
        outer.setBackground(Color.WHITE)

        pnl = JPanel()
        pnl.setLayout(None)
        pnl.setBackground(Color.WHITE)
        pnl.setPreferredSize(Dimension(900, 520))

        def hdr(txt, y):
            l = JLabel(txt)
            l.setFont(Font("Dialog", Font.BOLD, 13))
            l.setForeground(C_ORANGE)
            l.setBounds(20, y, 700, 24)
            pnl.add(l)

        def lbl(txt, y):
            l = JLabel(txt)
            l.setFont(Font("Dialog", Font.PLAIN, 12))
            l.setForeground(Color(0x333333))
            l.setBounds(20, y, 760, 22)
            pnl.add(l)

        def sep(y):
            line = JLabel()
            line.setOpaque(True)
            line.setBackground(Color(0xDDDDDD))
            line.setBounds(20, y, 760, 1)
            pnl.add(line)

        # ── Auto-save ───────────────────────────────────────────────────────
        hdr("Auto-Save", 18)
        lbl("Automatically export every N captured requests (0 = off):", 48)

        self._auto_n_fld = JTextField("0", 6)
        self._auto_n_fld.setFont(Font("Dialog", Font.PLAIN, 12))
        self._auto_n_fld.setBounds(20, 74, 70, 26)
        pnl.add(self._auto_n_fld)

        n_lbl = JLabel("requests  (set 0 to disable)")
        n_lbl.setFont(Font("Dialog", Font.PLAIN, 12))
        n_lbl.setForeground(Color(0x666666))
        n_lbl.setBounds(98, 74, 300, 26)
        pnl.add(n_lbl)

        lbl("Auto-save destination file:", 110)
        self._auto_p_fld = JTextField("(not set)", 40)
        self._auto_p_fld.setEditable(False)
        self._auto_p_fld.setFont(Font("Dialog", Font.PLAIN, 11))
        self._auto_p_fld.setBackground(Color(0xF5F5F5))
        self._auto_p_fld.setForeground(Color(0x555555))
        self._auto_p_fld.setBounds(20, 136, 480, 26)
        pnl.add(self._auto_p_fld)

        pick = self._sbtn("Browse...", C_DARK, lambda e: self._pick_path())
        pick.setBounds(510, 136, 100, 26)
        pnl.add(pick)

        apply = self._sbtn("Apply", C_GREEN, lambda e: self._apply_auto())
        apply.setBounds(20, 174, 90, 28)
        pnl.add(apply)

        self._auto_status = JLabel("")
        self._auto_status.setFont(Font("Dialog", Font.ITALIC, 11))
        self._auto_status.setForeground(C_BLUE)
        self._auto_status.setBounds(122, 174, 500, 28)
        pnl.add(self._auto_status)

        sep(214)

        # ── How to use ──────────────────────────────────────────────────────
        hdr("How to Use BurpSaver", 226)

        steps = [
            ("1. Capture",   "Browse your target normally. BurpSaver records every request in Activity Store automatically."),
            ("2. Export",    "Click 'Export Session' at any time to save Proxy History + Repeater + Activity to a .bsave file."),
            ("3. Close Burp","Your session is safe. The .bsave file holds everything."),
            ("4. Load",      "Next session: click 'Load Session', pick your .bsave file. History restores instantly."),
            ("5. Refresh",   "Click 'Refresh' on the Proxy History tab to pull the current live Burp proxy history into view."),
        ]
        y = 256
        for step, desc in steps:
            sl = JLabel(step)
            sl.setFont(Font("Dialog", Font.BOLD, 12))
            sl.setForeground(C_BLUE)
            sl.setBounds(20, y, 110, 20)
            pnl.add(sl)
            dl = JLabel(desc)
            dl.setFont(Font("Dialog", Font.PLAIN, 12))
            dl.setForeground(Color(0x333333))
            dl.setBounds(136, y, 640, 20)
            pnl.add(dl)
            y += 26

        sep(y + 6)

        # ── Where things appear after Load ──────────────────────────────────
        hdr("Where Loaded Data Appears", y + 18)
        targets = [
            ("Proxy History",  "BurpSaver 'Proxy History' tab  +  Burp Target -> Site map"),
            ("Repeater Store", "Real Burp Repeater tabs (check the Repeater tab in Burp's main nav)"),
            ("Activity Store", "BurpSaver 'Activity Store' tab"),
            ("Sitemap",        "Burp Target -> Site map"),
        ]
        ty = y + 48
        for k, v in targets:
            kl = JLabel(k)
            kl.setFont(Font("Dialog", Font.BOLD, 12))
            kl.setForeground(Color(0x444444))
            kl.setBounds(20, ty, 130, 20)
            pnl.add(kl)
            vl = JLabel("->  " + v)
            vl.setFont(Font("Dialog", Font.PLAIN, 12))
            vl.setForeground(Color(0x555555))
            vl.setBounds(156, ty, 600, 20)
            pnl.add(vl)
            ty += 24

        sp = _JSP(pnl)
        sp.setBorder(None)
        sp.getVerticalScrollBar().setUnitIncrement(16)
        outer.add(sp, BorderLayout.CENTER)
        return outer

    def _diag_tab(self):
        from javax.swing import JTextArea, JScrollPane as _JSP, JButton as _JBtn, Box
        from java.awt import BorderLayout as _BL, FlowLayout as _FL

        pnl = JPanel(BorderLayout())

        # Info bar
        info = JLabel(
            "  Diagnostics - logs byte conversion, setMessage calls, and errors. "
            "Click 'Refresh' after clicking a row in Proxy/Activity tabs.")
        info.setFont(Font("Dialog", Font.ITALIC, 11))
        info.setForeground(Color(0x555555))

        ref_btn = self._sbtn("Refresh Log", C_BLUE,
            lambda e: self._refresh_diag())
        clr_btn = self._sbtn("Clear Log", C_RED,
            lambda e: self._clear_diag())
        run_btn = self._sbtn("Run Byte Test", C_GREEN,
            lambda e: self._run_byte_test())

        bar = JPanel(FlowLayout(FlowLayout.LEFT, 6, 3))
        bar.setBackground(Color(0xF8F8F8))
        bar.setBorder(BorderFactory.createMatteBorder(0,0,1,0,Color(0xDDDDDD)))
        bar.add(info)
        bar.add(ref_btn)
        bar.add(clr_btn)
        bar.add(run_btn)
        pnl.add(bar, BorderLayout.NORTH)

        self._diag_area = JTextArea()
        self._diag_area.setEditable(False)
        self._diag_area.setFont(Font("Monospaced", Font.PLAIN, 11))
        self._diag_area.setBackground(Color(0xFAFAFA))
        self._diag_area.setText("Click 'Refresh Log' or interact with a row to see diagnostics.")
        sp = JScrollPane(self._diag_area)
        pnl.add(sp, BorderLayout.CENTER)
        return pnl

    def _refresh_diag(self):
        lines = _get_logs()
        text  = "\n".join(lines) if lines else "(no log entries yet)"
        SwingUtilities.invokeLater(lambda: self._diag_area.setText(text))

    def _clear_diag(self):
        with _LOG_LOCK:
            del _LOG_LINES[:]
        SwingUtilities.invokeLater(
            lambda: self._diag_area.setText("Log cleared."))

    def _run_byte_test(self):
        """Runs a self-contained byte conversion test and logs every step."""
        _log("=== BYTE TEST START ===")
        try:
            sample = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
            _log("sample type={} len={}".format(type(sample).__name__, len(sample)))

            # Step 1: direct ByteArrayOutputStream approach
            from java.io import ByteArrayOutputStream as _BAOS
            ba = bytearray(sample)
            baos = _BAOS(len(ba))
            for byte in ba:
                baos.write(int(byte))
            java_bytes = baos.toByteArray()
            _log("ByteArrayOutputStream result type={}".format(type(java_bytes).__name__))

            # Step 2: verify it is a real Java byte[]
            try:
                cls_name = java_bytes.getClass().getName()
                _log("Java class name: {} -- is byte[]? {}".format(
                    cls_name, cls_name == "[B"))
            except Exception as ce:
                _log("getClass() FAILED: {}".format(ce))

            # Step 3: setMessage on proxy viewer
            try:
                self._proxy_v._req_ed.setMessage(java_bytes, True)
                _log("setMessage(java_bytes, True) -> SUCCESS")
            except Exception as se:
                _log("setMessage FAILED: {}".format(se))

            # Step 4: _py_to_java_bytes full path
            result = _py_to_java_bytes(sample, log=_log)
            try:
                _log("_py_to_java_bytes Java class={}".format(
                    result.getClass().getName()))
            except Exception as ce:
                _log("_py_to_java_bytes getClass FAILED: {}".format(ce))

        except Exception as ex:
            import traceback
            _log("BYTE TEST EXCEPTION: " + traceback.format_exc())
        _log("=== BYTE TEST END ===")
        self._refresh_diag()

    def _south(self):
        south = JPanel(BorderLayout(0, 0))
        south.setBackground(Color(0xF4F6F7))
        south.setBorder(BorderFactory.createMatteBorder(1, 0, 0, 0, Color(0xCCCCCC)))

        # Hidden checkboxes - always all ticked; "Export Session" = save everything
        # Keep fields so _do_save() can read isSelected() without error
        _dummy = JPanel()
        self._chk_proxy = JCheckBox("Proxy History",  True)
        self._chk_rep   = JCheckBox("Repeater Store", True)
        self._chk_act   = JCheckBox("Activity Store", True)
        self._chk_site  = JCheckBox("Target Sitemap", True)
        # Not added to south - intentionally hidden

        # Progress
        self._prog = JProgressBar(0, 100)
        self._prog.setStringPainted(True)
        self._prog.setString("Ready")
        self._prog.setFont(Font("Dialog", Font.PLAIN, 11))
        self._prog.setPreferredSize(Dimension(0, 15))
        south.add(self._prog, BorderLayout.CENTER)

        # Buttons row
        btn_row = JPanel(BorderLayout(0, 0))
        btn_row.setBackground(Color(0xF4F6F7))

        btns = JPanel(FlowLayout(FlowLayout.LEFT, 6, 3))
        btns.setBackground(Color(0xF4F6F7))
        btns.add(self._mbtn("Export Session",   C_GREEN,  self._on_save_all))
        btns.add(self._mbtn("Load Session",    C_BLUE,   self._on_load))
        btns.add(self._mbtn("Refresh",         C_PURPLE, self._on_refresh_proxy))
        self._status_lbl = JLabel("  Capturing live traffic...")
        self._status_lbl.setFont(Font("Dialog", Font.PLAIN, 11))
        self._status_lbl.setForeground(Color(0x444444))
        btns.add(self._status_lbl)
        btn_row.add(btns, BorderLayout.CENTER)

        # Creator label - bottom right, plain text
        creator = JLabel(CREATOR + "  ")
        creator.setFont(Font("Dialog", Font.PLAIN, 11))
        creator.setForeground(Color(0x888888))
        creator_wrap = JPanel(FlowLayout(FlowLayout.RIGHT, 6, 3))
        creator_wrap.setBackground(Color(0xF4F6F7))
        creator_wrap.add(creator)
        btn_row.add(creator_wrap, BorderLayout.EAST)

        south.add(btn_row, BorderLayout.SOUTH)
        return south

    def _mbtn(self, text, color, listener):
        b = JButton(text)
        b.setBackground(color)
        b.setForeground(Color.WHITE)
        b.setFocusPainted(False)
        b.setFont(Font("Dialog", Font.BOLD, 12))
        b.setBorder(BorderFactory.createCompoundBorder(
            BorderFactory.createLineBorder(color.darker(), 1),
            BorderFactory.createEmptyBorder(4, 12, 4, 12)))
        b.addActionListener(listener)
        return b

    def _sbtn(self, text, color, listener):
        b = JButton(text)
        b.setBackground(color)
        b.setForeground(Color.WHITE)
        b.setFocusPainted(False)
        b.setFont(Font("Dialog", Font.PLAIN, 11))
        b.setBorder(BorderFactory.createCompoundBorder(
            BorderFactory.createLineBorder(color.darker(), 1),
            BorderFactory.createEmptyBorder(2, 8, 2, 8)))
        b.addActionListener(listener)
        return b

    def _chk(self, text, sel, parent):
        c = JCheckBox(text, sel)
        c.setFont(Font("Dialog", Font.PLAIN, 11))
        c.setBackground(Color(0xF4F6F7))
        parent.add(c)
        return c

    # ------------------------------------------------------------------ settings
    def _pick_path(self):
        ch = JFileChooser()
        ch.setDialogTitle("Auto-save destination")
        ch.setFileFilter(FileNameExtensionFilter(
            "BurpSaver (*.{})".format(FILE_EXT), FILE_EXT))
        ch.setSelectedFile(File("burp_autosave.{}".format(FILE_EXT)))
        if ch.showSaveDialog(self._panel) != JFileChooser.APPROVE_OPTION:
            return
        p = ch.getSelectedFile().getAbsolutePath()
        if not p.endswith("." + FILE_EXT):
            p += "." + FILE_EXT
        self._auto_path[0] = p
        self._auto_p_fld.setText(p)

    def _apply_auto(self):
        try:
            v = int(self._auto_n_fld.getText().strip())
            self._auto_n[0] = max(0, v)
            self._auto_status.setText(
                "Applied - every {} req -> {}".format(
                    self._auto_n[0], self._auto_path[0] or "(no file)"))
        except ValueError:
            self._auto_status.setText("Enter a valid integer.")

    # ------------------------------------------------------------------ clears
    def _clear_proxy(self):
        self._proxy_v.clear()
        SwingUtilities.invokeLater(
            lambda: self._tabs.setTitleAt(0, "Proxy History (0)"))
        self._set_status("Proxy viewer cleared.")

    def _clear_rep(self):
        self._rep_store = []
        self._rep_v.clear()
        SwingUtilities.invokeLater(
            lambda: self._tabs.setTitleAt(1, "Repeater Store (0)"))

    def _clear_act(self):
        n = len(self._act_store)
        if JOptionPane.showConfirmDialog(
                self._panel,
                "Clear all {} activity entries?".format(n),
                "Confirm", JOptionPane.YES_NO_OPTION) != JOptionPane.YES_OPTION:
            return
        with self._act_lock:
            self._act_store = []
        self._act_v.clear()
        SwingUtilities.invokeLater(
            lambda: self._tabs.setTitleAt(2, "Activity Store (0)"))
        self._act_lbl.setText("Live captured: 0")
        self._set_status("Activity store cleared.")

    # ------------------------------------------------------------------ repeater store
    def add_to_rep_store(self, messages, tab_name, tool="Manual"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for msg in messages:
            try:
                d = self._item_to_dict(msg)
                if not d:
                    continue
                d["tab_name"]    = tab_name
                d["tool"]        = tool
                d["captured_at"] = ts
                self._rep_store.append(d)
                entry = _Entry(d)
                # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
                row = [len(self._rep_store),
                       d.get("host", ""),
                       d.get("method", "?"),
                       d.get("url", ""),
                       "",
                       d.get("status", "-"),
                       str(d.get("length", 0)),
                       "",
                       "",
                       ts]
                # SINGLE call to batch_add - no duplication
                self._rep_v.batch_add([(entry, row)])
                SwingUtilities.invokeLater(lambda: self._tabs.setTitleAt(
                    1, "Repeater Store ({})".format(len(self._rep_store))))
            except Exception as ex:
                self._callbacks.printError("Rep store: " + str(ex))

    # ------------------------------------------------------------------ activity refresh
    def _do_refresh_act(self):
        self._set_prog(0, "Loading activity view...")
        with self._act_lock:
            snap = list(self._act_store)
        self._act_v.clear()
        total = len(snap)
        batch = []
        for i, d in enumerate(snap):
            entry = _Entry(d)
            # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
            row = [i + 1,
                   d.get("host",        ""),
                   d.get("method",      "?"),
                   d.get("url",         ""),
                   "",
                   d.get("status",      "-"),
                   str(d.get("length",  "-")),
                   "",
                   "",
                   d.get("captured_at", "")]
            batch.append((entry, row))
            if len(batch) >= 400:
                self._act_v.batch_add(list(batch))
                batch = []
                self._set_prog(int((i + 1) * 100.0 / max(total, 1)),
                               "Rendering {}/{}...".format(i + 1, total))
        if batch:
            self._act_v.batch_add(batch)
        self._set_prog(100, "Activity: {} entries".format(total))

    def _do_snap(self):
        self._set_prog(0, "Snapshotting Proxy History...")
        history = self._callbacks.getProxyHistory()
        total   = len(history)
        ts      = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        added   = 0
        for i, h in enumerate(history):
            try:
                d = self._item_to_dict(h)
                if d:
                    d["tool"] = "Proxy"; d["captured_at"] = ts
                    with self._act_lock:
                        self._act_store.append(d)
                    added += 1
            except Exception as ex:
                self._callbacks.printError("Snap: " + str(ex))
            if (i + 1) % 100 == 0:
                self._set_prog(int((i + 1) * 100.0 / max(total, 1)),
                               "Snapping {}/{}...".format(i + 1, total))
        with self._act_lock:
            nt = len(self._act_store)
        SwingUtilities.invokeLater(lambda t=nt: self._set_act_count(t))
        self._set_prog(100, "Snapshot: {} added".format(added))
        self._set_status("Snapshot: {} added.".format(added))

    # ------------------------------------------------------------------ button handlers
    def _on_refresh_proxy(self, _):
        self._bg(self._do_refresh_proxy)

    def _on_save(self, _):
        """Kept for compat; UI no longer exposes this directly."""
        self._on_save_all(None)

    def _on_save_all(self, _):
        p = self._save_path()
        if not p:
            return
        # Force ALL sections on
        for c in (self._chk_proxy, self._chk_rep,
                  self._chk_act, self._chk_site):
            c.setSelected(True)
        self._bg(self._do_save, p, False)

    def _on_load(self, _):
        ch = JFileChooser()
        ch.setDialogTitle("Load BurpSaver Project")
        ch.setFileFilter(FileNameExtensionFilter(
            "BurpSaver (*.{})".format(FILE_EXT), FILE_EXT))
        if ch.showOpenDialog(self._panel) != JFileChooser.APPROVE_OPTION:
            return
        self._bg(self._do_load, ch.getSelectedFile().getAbsolutePath())

    def _save_path(self):
        ch = JFileChooser()
        ch.setDialogTitle("Save BurpSaver Project")
        ch.setFileFilter(FileNameExtensionFilter(
            "BurpSaver (*.{})".format(FILE_EXT), FILE_EXT))
        ch.setSelectedFile(File("burp_{}.{}".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), FILE_EXT)))
        if ch.showSaveDialog(self._panel) != JFileChooser.APPROVE_OPTION:
            return None
        p = ch.getSelectedFile().getAbsolutePath()
        return p if p.endswith("." + FILE_EXT) else p + "." + FILE_EXT

    # ------------------------------------------------------------------ proxy preview
    def _do_refresh_proxy(self):
        self._set_prog(0, "Reading Proxy History...")
        history = self._callbacks.getProxyHistory()
        self._proxy_v.clear()
        total = len(history)
        ts    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        batch = []
        for i, h in enumerate(history):
            try:
                svc  = h.getHttpService()
                req  = h.getRequest()
                resp = h.getResponse()
                info = self._helpers.analyzeRequest(svc, req)
                status = length = "-"
                if resp:
                    ri     = self._helpers.analyzeResponse(resp)
                    status = str(ri.getStatusCode())
                    length = str(len(resp))
                d = {
                    "host":      str(svc.getHost()),
                    "port":      int(svc.getPort()),
                    "protocol":  str(svc.getProtocol()),
                    "url":       str(info.getUrl()),
                    "method":    str(info.getMethod()),
                    "request":   BurpExtender._raw_to_b64(req),
                    "response":  BurpExtender._raw_to_b64(resp),
                    "status": status, "length": length,
                    "comment": "", "highlight": "",
                }
                entry = _Entry(d)
                if i == 0:  # log first entry only to avoid spam
                    _log("LiveProxy[0]: req_raw type={} len={} b64_len={}".format(
                        type(entry._req).__name__, len(entry._req),
                        len(d.get("request",""))))
                    test_java = _py_to_java_bytes(entry._req, log=_log)
                    _log("LiveProxy[0]: java_bytes result type={} hasGetClass={}".format(
                        type(test_java).__name__,
                        hasattr(test_java, 'getClass')))
                # Derive richer columns for the extended table schema
                params_count = ""
                mime_type    = ""
                extension    = ""
                if resp:
                    try:
                        ri2       = self._helpers.analyzeResponse(resp)
                        mime_type = str(ri2.getStatedMimeType()) if ri2.getStatedMimeType() else ""
                    except Exception:
                        pass
                if req:
                    try:
                        params = info.getParameters()
                        params_count = str(len(params)) if params else ""
                    except Exception:
                        pass
                url_str = str(info.getUrl())
                try:
                    path = url_str.split("?")[0]
                    ext  = path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
                    extension = ext[:8]
                except Exception:
                    extension = ""
                # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
                row = [i + 1,
                       str(svc.getHost()),
                       str(info.getMethod()),
                       url_str,
                       params_count,
                       status,
                       length,
                       mime_type,
                       extension,
                       ts]
                batch.append((entry, row))
                if len(batch) >= 250:
                    self._proxy_v.batch_add(list(batch))
                    batch = []
                    self._set_prog(int((i + 1) * 100.0 / max(total, 1)),
                                   "Loading {}/{}...".format(i + 1, total))
            except Exception as ex:
                self._callbacks.printError("Preview: " + str(ex))
        if batch:
            self._proxy_v.batch_add(batch)
        cnt = self._proxy_v.count()
        SwingUtilities.invokeLater(
            lambda c=cnt: self._tabs.setTitleAt(0, "Proxy History ({})".format(c)))
        self._set_prog(100, "Proxy: {} entries".format(total))
        self._set_status("Proxy preview: {} entries".format(total))

    # ------------------------------------------------------------------ SAVE
    def _do_save(self, path, is_auto):
        if not self._save_lock.acquire(False):
            self._set_status("Save already running...")
            return
        writer = None
        try:
            self._set_prog(0, "Opening file...")
            writer = _FastWriter(path)
            writer.write_meta({
                "version":  VERSION,
                "saved_at": datetime.datetime.now().isoformat(),
                "tool":     EXT_NAME,
                "auto":     is_auto,
            })
            n_p = n_r = n_a = n_s = 0

            if self._chk_proxy.isSelected():
                hist  = self._callbacks.getProxyHistory()
                total = len(hist)
                self._set_prog(2, "Writing {} proxy entries...".format(total))
                for i, item in enumerate(hist):
                    try:
                        d = self._item_to_dict(item)
                        if d:
                            writer.write_proxy(d)
                            n_p += 1
                    except Exception as ex:
                        self._callbacks.printError("Proxy write: " + str(ex))
                    if i % 200 == 0:
                        self._set_prog(2 + int((i + 1) * 28.0 / max(total, 1)),
                                       "Proxy {}/{}...".format(i + 1, total))

            if self._chk_rep.isSelected():
                self._set_prog(32, "Writing Repeater store...")
                for d in self._rep_store:
                    try:
                        writer.write_repeater(d)
                        n_r += 1
                    except Exception as ex:
                        self._callbacks.printError("Rep write: " + str(ex))

            if self._chk_act.isSelected():
                with self._act_lock:
                    snap = list(self._act_store)
                total = len(snap)
                self._set_prog(36, "Writing {} activity entries...".format(total))
                for i, d in enumerate(snap):
                    try:
                        writer.write_activity(d)
                        n_a += 1
                    except Exception as ex:
                        self._callbacks.printError("Act write: " + str(ex))
                    if i % 300 == 0:
                        self._set_prog(36 + int((i + 1) * 46.0 / max(total, 1)),
                                       "Activity {}/{}...".format(i + 1, total))

            if self._chk_site.isSelected():
                self._set_prog(84, "Writing sitemap...")
                try:
                    for item in self._callbacks.getSiteMap(None):
                        d = self._item_to_dict(item)
                        if d:
                            writer.write_sitemap(d)
                            n_s += 1
                except Exception as ex:
                    self._callbacks.printError("Sitemap write: " + str(ex))

            writer.close()
            writer = None
            fsize = File(path).length() / 1024.0
            s = "proxy={} rep={} act={} site={} ({:.0f} KB)".format(
                n_p, n_r, n_a, n_s, fsize)
            self._set_prog(100, "Saved!  " + s)
            self._set_status("Saved: " + s)
            if not is_auto:
                JOptionPane.showMessageDialog(
                    self._panel,
                    ("Save complete!\n\n"
                     "  Proxy History  : {}\n"
                     "  Repeater Store : {}\n"
                     "  Activity Store : {}\n"
                     "  Sitemap        : {}\n"
                     "  Size           : {:.1f} KB (compressed)\n\n{}").format(
                        n_p, n_r, n_a, n_s, fsize, path),
                    EXT_NAME + " - Saved", JOptionPane.INFORMATION_MESSAGE)
        except Exception as ex:
            self._callbacks.printError("Save error:\n" + _tb.format_exc())
            if not is_auto:
                JOptionPane.showMessageDialog(
                    self._panel, "Save failed:\n" + str(ex),
                    EXT_NAME + " - Error", JOptionPane.ERROR_MESSAGE)
        finally:
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass
            self._save_lock.release()

    # ------------------------------------------------------------------ LOAD
    def _do_load(self, path):
        try:
            # Pass 1: count
            self._set_prog(0, "Scanning file...")
            counts = {}
            meta   = {}

            def count_cb(s, d):
                if s == "meta":
                    meta.update(d)
                counts[s] = counts.get(s, 0) + 1

            _read_ndjson(path, count_cb)

            n_p = counts.get("proxy",    0)
            n_r = counts.get("repeater", 0)
            n_a = counts.get("activity", 0)
            n_s = counts.get("sitemap",  0)
            self._set_prog(5, "Scan done. Showing import options...")

            options = [
                "All  (proxy + repeater + activity + sitemap)",
                "Proxy History + Sitemap only",
                "Activity Store only",
                "Repeater Store only",
                "Cancel",
            ]
            choice = JOptionPane.showOptionDialog(
                self._panel,
                ("File   : {}\nSaved  : {}\n\n"
                 "Contents:\n"
                 "  Proxy History  : {}\n"
                 "  Repeater Store : {}\n"
                 "  Activity Store : {}\n"
                 "  Sitemap        : {}\n\n"
                 "What would you like to restore?").format(
                    path, meta.get("saved_at", "?"),
                    n_p, n_r, n_a, n_s),
                EXT_NAME + " - Import",
                JOptionPane.DEFAULT_OPTION,
                JOptionPane.QUESTION_MESSAGE,
                None, options, options[0])

            if choice < 0 or choice == 4:
                self._set_prog(0, "Cancelled.")
                return

            do_p = choice in (0, 1)
            do_s = choice in (0, 1)
            do_a = choice in (0, 2)
            do_r = choice in (0, 3)

            want = ((n_p if do_p else 0) + (n_r if do_r else 0) +
                    (n_a if do_a else 0) + (n_s if do_s else 0)) or 1

            ok_p = [0]; ok_r = [0]; ok_a = [0]; ok_s = [0]
            done = [0]

            def tick(label):
                done[0] += 1
                self._set_prog(min(int(done[0] * 94.0 / want), 94), label)

            if do_p: self._proxy_v.clear()
            if do_a: self._act_v.clear()

            saved_ts  = meta.get("saved_at", "")[:19]
            p_batch   = []
            a_batch   = []
            a_dicts   = []

            self._set_prog(6, "Restoring...")

            def restore_cb(section, e):
                if section == "meta":
                    return

                if section == "proxy" and do_p:
                    try:
                        self._push_sitemap(e)
                        ok_p[0] += 1
                        entry = _Entry(e)
                        # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
                        row = [ok_p[0],
                               e.get("host", ""),
                               e.get("method", "?"),
                               e.get("url", ""),
                               "",
                               e.get("status", "-"),
                               str(e.get("length", "-")),
                               "",
                               "",
                               saved_ts]
                        p_batch.append((entry, row))
                        if len(p_batch) >= 300:
                            self._proxy_v.batch_add(list(p_batch))
                            del p_batch[:]
                    except Exception as ex:
                        self._callbacks.printError("Proxy load: " + str(ex))
                    tick("Proxy {}/{}...".format(ok_p[0], n_p))

                elif section == "repeater" and do_r:
                    try:
                        self._push_repeater(e)
                        ok_r[0] += 1
                    except Exception as ex:
                        self._callbacks.printError("Rep load: " + str(ex))
                    tick("Repeater {}/{}...".format(ok_r[0], n_r))

                elif section == "activity" and do_a:
                    a_dicts.append(e)
                    entry = _Entry(e)
                    # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
                    row = [ok_a[0] + 1,
                           e.get("host", ""),
                           e.get("method", "?"),
                           e.get("url", ""),
                           "",
                           e.get("status", "-"),
                           str(e.get("length", "-")),
                           "",
                           "",
                           e.get("captured_at", saved_ts)]
                    a_batch.append((entry, row))
                    ok_a[0] += 1
                    if len(a_batch) >= 500:
                        self._act_v.batch_add(list(a_batch))
                        ab = list(a_dicts)
                        with self._act_lock:
                            self._act_store.extend(ab)
                            t2 = len(self._act_store)
                        del a_batch[:]
                        del a_dicts[:]
                        SwingUtilities.invokeLater(
                            lambda tv=t2: self._set_act_count(tv))
                    tick("Activity {}/{}...".format(ok_a[0], n_a))

                elif section == "sitemap" and do_s:
                    try:
                        self._push_sitemap(e)
                        ok_s[0] += 1
                    except Exception as ex:
                        self._callbacks.printError("Sitemap load: " + str(ex))
                    tick("Sitemap {}/{}...".format(ok_s[0], n_s))

            _read_ndjson(path, restore_cb)

            # Flush
            if p_batch:
                self._proxy_v.batch_add(p_batch)
            if a_batch:
                self._act_v.batch_add(a_batch)
            if a_dicts:
                with self._act_lock:
                    self._act_store.extend(a_dicts)
                    t2 = len(self._act_store)
                SwingUtilities.invokeLater(lambda tv=t2: self._set_act_count(tv))

            def _titles():
                if do_p:
                    self._tabs.setTitleAt(0, "Proxy History ({})".format(self._proxy_v.count()))
                if do_r:
                    self._tabs.setTitleAt(1, "Repeater Store ({})".format(len(self._rep_store)))
                if do_a:
                    self._tabs.setTitleAt(2, "Activity Store ({})".format(self._act_v.count()))
            SwingUtilities.invokeLater(_titles)

            self._set_prog(100, "Load complete!")
            self._set_status("Loaded: proxy={} rep={} act={} site={}".format(
                ok_p[0], ok_r[0], ok_a[0], ok_s[0]))

            JOptionPane.showMessageDialog(
                self._panel,
                ("Load complete!\n\n"
                 "  Proxy History  : {} -> BurpSaver tab + Target->Site map\n"
                 "  Repeater tabs  : {} -> Check Burp Repeater tab\n"
                 "  Activity Store : {} -> BurpSaver Activity tab\n"
                 "  Sitemap        : {} -> Target -> Site map\n\n"
                 "Saved at: {}").format(
                    ok_p[0], ok_r[0], ok_a[0], ok_s[0],
                    meta.get("saved_at", "?")),
                EXT_NAME + " - Loaded", JOptionPane.INFORMATION_MESSAGE)

        except Exception as ex:
            self._callbacks.printError("Load error:\n" + _tb.format_exc())
            JOptionPane.showMessageDialog(
                self._panel, "Load failed:\n" + str(ex),
                EXT_NAME + " - Error", JOptionPane.ERROR_MESSAGE)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _raw_to_b64(data):
        """Safely convert ANY Jython/Java byte sequence to a base64 ASCII string.

        On Windows Jython, IHttpRequestResponse.getRequest()/getResponse()
        returns array.array (Jython-wrapped Java byte[]).
        bytes(array.array) calls str() -> 'array('b',[...])' - WRONG.
        array.array.tostring() returns the correct raw byte string.
        """
        if data is None:
            return ""
        t = type(data).__name__
        if t == "array":
            # Jython array.array: .tostring() gives raw bytes as a Python str
            raw = data.tostring()
        elif isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data   # Jython str from Java API is already raw bytes
        else:
            # Last resort: iterate and pack as bytearray
            try:
                raw = bytearray(int(b) & 0xFF for b in data).decode("iso-8859-1")
            except Exception:
                raw = ""
        return base64.b64encode(raw).decode("ascii")

    def _item_to_dict(self, item):
        try:
            svc  = item.getHttpService()
            req  = item.getRequest()
            resp = item.getResponse()
            info = self._helpers.analyzeRequest(svc, req) if req else None
            _log("_item_to_dict: req type={} req len={} resp len={}".format(
                type(req).__name__,
                len(req) if req else 0,
                len(resp) if resp else 0))
            req_b64  = self._raw_to_b64(req)
            resp_b64 = self._raw_to_b64(resp)
            _log("_item_to_dict: req_b64_len={} resp_b64_len={}".format(
                len(req_b64), len(resp_b64)))
            d = {
                "host":      str(svc.getHost())     if svc  else "",
                "port":      int(svc.getPort())      if svc  else 443,
                "protocol":  str(svc.getProtocol())  if svc  else "https",
                "url":       str(info.getUrl())       if info else "",
                "method":    str(info.getMethod())    if info else "",
                "request":   req_b64,
                "response":  resp_b64,
                "status":    "",
                "length":    0,
                "comment":   str(item.getComment())   if item.getComment()   else "",
                "highlight": str(item.getHighlight())  if item.getHighlight() else "",
            }
            if resp:
                ri = self._helpers.analyzeResponse(resp)
                d["status"] = str(ri.getStatusCode())
                d["length"] = len(resp)
            return d
        except Exception as ex:
            self._callbacks.printError("_item_to_dict: " + str(ex))
            _log("_item_to_dict ERROR: " + str(ex))
            return None

    def _push_sitemap(self, e):
        req_raw  = base64.b64decode(e["request"])  if e.get("request")  else None
        resp_raw = base64.b64decode(e["response"]) if e.get("response") else None
        if not req_raw:
            return
        svc = self._helpers.buildHttpService(
            str(e["host"]), int(e.get("port", 443)), str(e.get("protocol", "https")))
        si = _SitemapItem(svc, req_raw, resp_raw,
                          e.get("comment", ""), e.get("highlight", ""))
        saved = self._callbacks.saveBuffersToTempFiles(si)
        self._callbacks.addToSiteMap(saved)

    def _push_repeater(self, e):
        req_raw = base64.b64decode(e["request"]) if e.get("request") else None
        if not req_raw:
            return
        host      = str(e.get("host", ""))
        port      = int(e.get("port", 443))
        use_https = str(e.get("protocol", "https")).lower() == "https"
        tab_name  = str(e.get("tab_name", "Restored"))
        self._callbacks.sendToRepeater(
            host, port, use_https, _py_to_java_bytes(req_raw), tab_name)
        self._rep_store.append(e)
        entry = _Entry(e)
        # [#, Host, Method, URL, Params, Status, Length, MIME type, Extension, Time]
        row = [len(self._rep_store),
               e.get("host", ""),
               e.get("method", "?"),
               e.get("url", ""),
               "",
               e.get("status", "-"),
               str(e.get("length", 0)),
               "",
               "",
               e.get("captured_at", "")]
        self._rep_v.batch_add([(entry, row)])

    def _set_prog(self, val, txt):
        def _u():
            self._prog.setValue(val)
            self._prog.setString(txt)
        SwingUtilities.invokeLater(_u)

    def _set_status(self, txt):
        SwingUtilities.invokeLater(
            lambda: self._status_lbl.setText("  " + txt))

    def extensionUnloaded(self):
        self._callbacks.printOutput("[{}] Unloaded.".format(EXT_NAME))


# =============================================================================
#  Context menu
# =============================================================================
class _CtxMenu(IContextMenuFactory):
    def __init__(self, ext):
        self._ext = ext

    def createMenuItems(self, invocation):
        items = ArrayList()
        m1 = JMenuItem("BurpSaver: Add to Repeater Store")
        m1.addActionListener(lambda e: self._add_rep(invocation))
        items.add(m1)
        m2 = JMenuItem("BurpSaver: Save All Activity Now")
        m2.addActionListener(lambda e: self._ext._on_save_all(None))
        items.add(m2)
        m3 = JMenuItem("BurpSaver: Add Selected to Activity Store")
        m3.addActionListener(lambda e: self._add_act(invocation))
        items.add(m3)
        return items

    def _add_rep(self, invocation):
        msgs = invocation.getSelectedMessages()
        if not msgs:
            return
        name = "Repeater-{}".format(len(self._ext._rep_store) + 1)
        self._ext.add_to_rep_store(list(msgs), name, "Manual")

    def _add_act(self, invocation):
        msgs = invocation.getSelectedMessages()
        if not msgs:
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for msg in msgs:
            try:
                d = self._ext._item_to_dict(msg)
                if d:
                    d["tool"] = "Manual"; d["captured_at"] = ts
                    with self._ext._act_lock:
                        self._ext._act_store.append(d)
                        total = len(self._ext._act_store)
                    SwingUtilities.invokeLater(
                        lambda t=total: self._ext._set_act_count(t))
            except Exception as ex:
                self._ext._callbacks.printError("Add act: " + str(ex))
