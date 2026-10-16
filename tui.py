"""Terminal input handling: raw mode, key decoding and inline pickers."""

import base64
import os
import select
import shutil
import subprocess
import sys
import time
import termios
import tty
from contextlib import contextmanager

from rich.console import Group
from rich.panel import Panel

from ui import accent, as_typed, bright, build_layout, console, detail_panel

ESCAPE = "\x1b"        # a bare Escape, not part of an escape sequence
KEY_UP = "\x1b[A"
KEY_DOWN = "\x1b[B"
KEY_LEFT = "\x1b[D"
KEY_RIGHT = "\x1b[C"
KEY_PGUP = "\x1b[5~"
# ctrl+shift+up / ctrl+shift+down: select the line above or below. Terminals
# send these as CSI 1 ; 6 A / B, where 6 is shift+ctrl in the modifier bits.
# Sent as internal tokens rather than raw sequences so the buffer can tell them
# apart from a plain arrow.
KEY_SELECT_UP = "\x00select-up"
KEY_SELECT_DOWN = "\x00select-down"
# ctrl+left / ctrl+right move by a word; with shift they select by one. Same
# modifier scheme as the arrows above, so 5 is ctrl and 6 is ctrl+shift.
KEY_WORD_LEFT = "\x00word-left"
KEY_WORD_RIGHT = "\x00word-right"
KEY_SELECT_WORD_LEFT = "\x00select-word-left"
KEY_SELECT_WORD_RIGHT = "\x00select-word-right"
# Deleting the word to the left of the cursor. Terminals disagree about how to
# send ctrl+backspace: some send a distinct sequence, many send the same byte
# as an ordinary backspace. So this is bound to every unambiguous form, and
# ctrl+w is the one that works everywhere.
KEY_DELETE_WORD_LEFT = "\x00delete-word-left"
KEY_PGDN = "\x1b[6~"
KEY_DELETE = "\x1b[3~"
# ctrl+shift+c / ctrl+shift+v reach the program only on terminals that do not
# claim them; the kitty keyboard protocol spells them out like this.
KEY_COPY = "\x00copy"
KEY_PASTE = "\x00paste"
KEY_WHEEL_UP = "\x00wheel-up"
KEY_WHEEL_DOWN = "\x00wheel-down"
KEY_HOME = "\x1b[H"
KEY_END = "\x1b[F"

ESCAPE_KEYS = {
    b"\x1b[A": KEY_UP,
    b"\x1b[B": KEY_DOWN,
    b"\x1b[D": KEY_LEFT,
    b"\x1b[C": KEY_RIGHT,
    b"\x1b[H": KEY_HOME,
    b"\x1b[F": KEY_END,
    b"\x1b[5~": KEY_PGUP,
    b"\x1b[6~": KEY_PGDN,
    b"\x1b[3~": KEY_DELETE,
    b"\x1b[1;6A": KEY_SELECT_UP,
    b"\x1b[1;6B": KEY_SELECT_DOWN,
    # Some terminals send shift on its own as ;2, and a few drop the 1;
    b"\x1b[1;2A": KEY_SELECT_UP,
    b"\x1b[1;2B": KEY_SELECT_DOWN,
    b"\x1b[;6A": KEY_SELECT_UP,
    b"\x1b[;6B": KEY_SELECT_DOWN,
    b"\x1b[1;5C": KEY_WORD_RIGHT,
    b"\x1b[1;5D": KEY_WORD_LEFT,
    b"\x1b[1;6C": KEY_SELECT_WORD_RIGHT,
    b"\x1b[1;6D": KEY_SELECT_WORD_LEFT,
    b"\x1b[;5C": KEY_WORD_RIGHT,
    b"\x1b[;5D": KEY_WORD_LEFT,
    b"\x1b[;6C": KEY_SELECT_WORD_RIGHT,
    b"\x1b[;6D": KEY_SELECT_WORD_LEFT,
    b"\x1b[1;2C": KEY_SELECT_WORD_RIGHT,
    b"\x1b[1;2D": KEY_SELECT_WORD_LEFT,
    # ctrl+backspace, where the terminal spells it out
    b"\x1b[127;5u": KEY_DELETE_WORD_LEFT,
    b"\x1b[3;5~": KEY_DELETE_WORD_LEFT,
    b"\x1b[27;5~": KEY_DELETE_WORD_LEFT,
    # The kitty protocol spells ctrl+shift+c as CSI 99 ; 6 u (99 is c, 6 is
    # ctrl+shift); some terminals report the shifted codepoint instead (67),
    # and some drop the shift bit it to 5. ctrl+shift+v is 118 for the same
    # reason, with 86 for the shifted spelling. ctrl+c alone is 99 ; 5 u and
    # is left as a plain ctrl+c, never a copy.
    b"\x1b[99;6u": KEY_COPY,
    b"\x1b[67;6u": KEY_COPY,
    b"\x1b[99;2u": KEY_COPY,
    b"\x1b[118;6u": KEY_PASTE,
    b"\x1b[86;6u": KEY_PASTE,
    b"\x1b[118;5u": KEY_PASTE,
    b"\x1b[118;2u": KEY_PASTE,
}

# Five rows at a time in every list inside the Menu - submenus and pickers
# alike. A list that drew every option at once grew down the screen until the
# dashboard behind it was pushed off, and on a short terminal left the list
# itself cropped with nothing to scroll it. Anything past the fifth is reached
# with the arrows, the wheel or the page keys, which already move the window
# with the highlight.
LIST_MAX = 5
# What a list's own box costs: a border top and bottom, the blank line and the
# key hint. A list is allowed to push the dashboard off the top rather than
# shrink itself - the dashboard behind a menu is context, not content, and
# budgeting for both is what left a six-entry submenu showing three rows.
PICKER_CHROME = 4


MOUSE_ON = "\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1006l\x1b[?1003l\x1b[?1002l\x1b[?1000l"
# Bracketed paste tells the terminal to wrap pasted text in ESC[200~ / ESC[201~.
# Without asking for it you are at the terminal's mercy: some send the markers,
# some send bare characters, and a paste that lands as escape sequences is
# swallowed by the escape parser and silently lost.
PASTE_ON = "\x1b[?2004h"
PASTE_OFF = "\x1b[?2004l"


def write_escape(seq):
    """Write a control sequence straight to the terminal.

    Deliberately not sys.stdout: while a field is open Rich's Live swaps stdout
    for a proxy, so anything written there was captured and thrown away. The
    mouse release and the bracketed-paste request were both being generated at
    exactly that moment and silently dropped, which is why copying and pasting
    did nothing inside the editor.

    Skipped entirely when stdout is not a terminal: control sequences on a pipe
    or in a file are just noise.
    """
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            return
    except (AttributeError, ValueError, OSError):
        pass
    try:
        stream.write(seq)
        stream.flush()
    except (OSError, ValueError, AttributeError):
        pass


@contextmanager
def raw_mode():
    if not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        # Clear ISIG so Ctrl+C arrives as the \x03 byte instead of SIGINT.
        # That lets the pickers cancel on Ctrl+C and the menu exit cleanly.
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ISIG
        # IXON too: ctrl+s is XOFF, so with software flow control left on the
        # line discipline eats it and the app never sees the save key - the
        # terminal just stops printing. ctrl+q (XON) has the same problem.
        attrs[0] &= ~(termios.IXON | getattr(termios, "IXANY", 0))
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # Claim mouse events so the terminal stops reporting the wheel and
        # pointer movement as arrow keys, which moved the menu highlight.
        write_escape(MOUSE_ON)
        write_escape(PASTE_ON)
        yield
    finally:
        write_escape(PASTE_OFF)
        write_escape(MOUSE_OFF)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_seq_byte(fd, timeout):
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    try:
        return os.read(fd, 1) or None
    except (InterruptedError, OSError):
        return None


class Pasted:
    """Text handed over by the terminal in one go, rather than keystrokes."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"Pasted({self.text!r})"

    def __eq__(self, other):
        return isinstance(other, Pasted) and other.text == self.text

    def __hash__(self):
        return hash(("pasted", self.text))


def _read_paste(fd):
    """Collect everything up to the ESC[201~ that ends a bracketed paste."""
    text = bytearray()
    while True:
        byte = read_seq_byte(fd, 0.05)
        if byte is None:
            break
        if byte == b"\x1b":
            # Read exactly the five bytes after ESC: "[201~". "[" is itself a
            # legal CSI final byte, so stopping at the first one would cut the
            # marker in half and paste the rest of it in as text.
            marker = bytearray()
            for _ in range(5):
                nxt = read_seq_byte(fd, 0.05)
                if nxt is None:
                    break
                marker += nxt
            if bytes(marker) == b"[201~":
                break
            # An escape that was not the end marker is part of the text.
            text += byte + bytes(marker)
            continue
        text += byte
    return Pasted(text.decode("utf-8", "replace"))


# A byte drain_escape read while looking for a sequence's second byte, but
# which turned out to begin a key of its own: a second fast Escape, or a digit
# pressed on Escape's heels. read_key serves it before touching the terminal.
_PUSHED = b""


def push_back(byte):
    global _PUSHED
    _PUSHED = byte + _PUSHED


def drain_escape(fd):
    """Interpret an ESC-led sequence.

    A recognised key returns its token, "\\x1b" means Escape was pressed alone,
    and everything else - mouse reports, function keys we do not use - is fully
    consumed and ignored. Consuming the whole sequence matters: leaving a stray
    byte behind would have it read as the next keystroke.
    """
    ready, _, _ = select.select([fd], [], [], 0)
    if not ready:
        return "\x1b"
    nxt = read_seq_byte(fd, 0.05)
    if nxt in (b"\r", b"\n"):
        return SHIFT_ENTER          # ESC then Enter: how some terminals send it
    if nxt in (b"\x7f", b"\x08"):
        return KEY_DELETE_WORD_LEFT        # alt+backspace, the portable spelling
    if nxt is None:
        return "\x1b"
    if nxt not in (b"[", b"O"):
        # Esc then something that is not a sequence: that byte began its own
        # key. Swallowing it made a second Esc vanish - two presses backed out
        # one level - and ate a digit typed right after an Esc.
        push_back(nxt)
        return "\x1b"
    body = read_seq_byte(fd, 0.05)
    if body is None:
        return ESCAPE_KEYS.get(b"\x1b" + nxt)
    seq = b"\x1b" + nxt + body
    if nxt == b"[" and body == b"2":
        # ESC[200~ opens a bracketed paste. Read on only while what has been
        # read is still the start of that marker, and keep every byte: the
        # earlier version swallowed three bytes and dropped them, so anything
        # else beginning with "[2" - CSI 2~, CSI 27;5~ - arrived mangled.
        marker = b"\x1b[200~"
        while len(seq) < len(marker) and marker.startswith(seq):
            byte = read_seq_byte(fd, 0.05)
            if byte is None:
                break
            seq += byte
        if seq == marker:
            return _read_paste(fd)
        # The byte that broke the match may itself have finished the sequence:
        # CSI 2~ ends at "~" and must not swallow whatever follows it.
        if len(seq) > 2 and 0x40 <= seq[-1] <= 0x7E:
            return ESCAPE_KEYS.get(seq)
    # X10 mouse report: ESC [ M followed by three raw bytes.
    if nxt == b"[" and body == b"M":
        for _ in range(3):
            read_seq_byte(fd, 0.02)
        return None
    if nxt == b"[" and body == b"<":
        # SGR mouse report: ESC [ < button ; column ; row (M press / m release)
        report = b""
        while True:
            byte = read_seq_byte(fd, 0.02)
            if byte is None:
                break
            report += byte
            if byte in (b"M", b"m"):
                break
        return _mouse_event(report)
    if 0x40 <= body[0] <= 0x7E:          # already the final byte
        return ESCAPE_KEYS.get(seq)
    while True:
        byte = read_seq_byte(fd, 0.02)
        if byte is None:
            break
        seq += byte
        if 0x40 <= byte[0] <= 0x7E:      # CSI final byte ends the sequence
            break
    return ESCAPE_KEYS.get(seq)


def _mouse_event(report):
    """Turn an SGR mouse report into a key, or None to ignore it.

    Only the wheel is acted on. Presses, drags and releases are swallowed: they
    are only sent because mouse reporting is on, and letting them through would
    type stray characters into whatever field is open."""
    parts = report.lstrip(b"<").rstrip(b"Mm").split(b";")
    if len(parts) < 1:
        return None
    try:
        button = int(parts[0])
    except ValueError:
        return None
    if button == 64:
        return KEY_WHEEL_UP
    if button == 65:
        return KEY_WHEEL_DOWN
    return None


def read_key(timeout=None):
    fd = sys.stdin.fileno()
    if not sys.stdin.isatty():
        try:
            return sys.stdin.read(1) or None
        except (InterruptedError, OSError):
            return None
    global _PUSHED
    if _PUSHED:
        # A byte a sequence read decided belonged to the next key.
        char, _PUSHED = _PUSHED[:1], _PUSHED[1:]
    else:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        while True:
            try:
                char = os.read(fd, 1)
                break
            except InterruptedError:
                continue
            except OSError:
                return None
        if not char:
            return None
    key = char.decode("utf-8", "replace")
    if key != "\x1b":
        # ctrl+x u / r / q is resolved here so every screen gets it, including
        # pickers and editors that read keys directly. ctrl+x on its own is
        # swallowed rather than passed on: left as a raw \x18 it would be typed
        # into a field whenever nobody followed it with u, r or q.
        if key == CTRL_X:
            read_chord(key)
            return None
        return key
    return drain_escape(fd)


def list_view(limit=None):
    """How many rows of a list to draw at once.

    A picker leaves room for the dashboard behind it. A submenu does not: it
    counts only what its own box needs, so it keeps all five rows on a screen
    where a picker would be squeezed to three."""
    cap = limit or LIST_MAX
    return max(2, min(cap, console.height - PICKER_CHROME))


def fit_top(idx, top, n, view):
    top = max(0, min(top, n - view))
    if idx < top:
        return idx
    if idx >= top + view:
        return idx - view + 1
    return top


def prepare_rows(items):
    """(names, rows) for the picker.

    A row is ('h', header) or ('i', name_index, number). `number` is None for
    unnumbered rows, which are skipped when counting. An item may be a plain
    string, (group, name), or (group, name, numbered).
    """
    if items and isinstance(items[0], tuple) and len(items[0]) == 2:
        names, rows, last = [], [], None
        for group, name in items:
            if group and group != last:
                rows.append(("h", group))
                last = group
            rows.append(("i", len(names), len(names) + 1))
            names.append(name)
        return names, rows
    names, rows, count = [], [], 0
    for item in items:
        name = item[1] if isinstance(item, tuple) else item
        numbered = not (isinstance(item, tuple) and len(item) > 2 and not item[2])
        if numbered:
            count += 1
            rows.append(("i", len(names), count))
        else:
            rows.append(("i", len(names), None))
        names.append(name)
    return names, rows


def step_row(rows, cur, delta):
    """Move to the next or previous item row, wrapping round at the ends.

    Going past the last option lands on the first, and past the first on the
    last, so a short list can be stepped all the way through without reaching
    for anything else. Group headers are stepped over on the way, including
    when wrapping."""
    total = len(rows)
    if not total:
        return cur
    i = cur
    for _ in range(total):
        i = (i + delta) % total
        if rows[i][0] == "i":
            return i
    return cur              # nothing selectable at all


def input_line(value, placeholder=None, cursor=None):
    """The `> ` line, with a dim placeholder shown while the field is empty.

    `cursor` is an index into `value`; when given, the block is drawn there so
    the position is visible, which matters once a field wraps onto several
    lines."""
    if cursor is None:
        if value:
            return f"> {as_typed(value)}{caret()}"
        if placeholder:
            return f"> [dim]{placeholder}[/]{caret()}"
        return f"> {caret()}"
    at = max(0, min(cursor, len(value)))
    return f"> {as_typed(value[:at])}{caret()}{as_typed(value[at:])}"


# An open field takes the whole terminal, so the only things competing with the
# text are the box borders, the prompt, the key hint and the scroll markers.
BOX_LINES = 8
MIN_FIELD_ROWS = 3

# The caret blinks the way a terminal's own does. A steady block left in a
# saved panel looked like a stray character rather than a cursor.
BLINK_SECONDS = 0.5
_blink = {"on": True, "at": 0.0}


def blink_state(force=None):
    """Whether the caret should be drawn right now.

    force=True snaps it back on, which is what happens after a keypress: you
    type, the caret is there, and it only fades after a pause."""
    now = time.monotonic()
    if force is not None:
        _blink["on"] = bool(force)
        _blink["at"] = now
    elif now - _blink["at"] >= BLINK_SECONDS:
        _blink["on"] = not _blink["on"]
        _blink["at"] = now
    return _blink["on"]


def cursor_row(buffer):
    """Index of the line the cursor is on."""
    for i, (_text, col, _selection) in enumerate(buffer.lines()):
        if col is not None:
            return i
    return len(buffer.lines()) - 1


def field_rows():
    """How many lines of text fit, at the current terminal size."""
    return max(MIN_FIELD_ROWS, console.height - BOX_LINES)


def scroll_to(cursor_row, top, total, rows):
    """Scroll offset that keeps the cursor's line on screen."""
    if cursor_row < top:
        return cursor_row
    if cursor_row >= top + rows:
        return cursor_row - rows + 1
    return top


# Copy and paste. The terminal owns the clipboard, so copying hands the text
# over with OSC 52 - which works over ssh, where a local clipboard tool cannot.
# Pasting is the other way round: there is no way to ask a terminal what is on
# the clipboard, so the system clipboard is read directly if a tool for it is
# installed.
CLIPBOARD_TOOLS = (("wl-paste", ["wl-paste", "--no-newline"]),
                   ("xclip", ["xclip", "-selection", "clipboard", "-o"]),
                   ("xsel", ["xsel", "--clipboard", "--output"]),
                   ("pbpaste", ["pbpaste"]))


# How to read the system clipboard. A terminal program cannot ask for it any
# other way - the clipboard lives outside the process - so this shells out to
# whichever tool the machine happens to have.
CLIPBOARD_READERS = (
    ("xclip", ["xclip", "-selection", "clipboard", "-o"]),
    ("wl-paste", ["wl-paste", "--no-newline"]),
    ("xsel", ["xsel", "--clipboard", "--output"]),
    ("pbpaste", ["pbpaste"]),
    ("powershell", ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]),
)


def _clipboard_readers():
    """The clipboard tools to try, best fit for this session first.

    Both xclip and wl-paste can be installed on a Wayland desktop, where X is
    only there for the old applications. Trying xclip first meant reading the
    X11 clipboard - which nothing had written to in weeks - and pasting that,
    or nothing at all, while the clipboard someone was copying from sat full
    and unread next to it."""
    import shutil
    import subprocess
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    wanted = ["wl-paste", "xclip", "xsel", "pbpaste", "powershell"] if wayland \
        else ["xclip", "xsel", "pbpaste", "wl-paste", "powershell"]
    for name in wanted:
        for tool, command in CLIPBOARD_READERS:
            if tool == name and shutil.which(name):
                yield command


def clipboard_paste():
    """Text from the system clipboard, or None if it cannot be read.

    ctrl+shift+v is usually swallowed by the terminal, which pastes on our
    behalf. This is for ctrl+v, which reaches the program and was otherwise a
    dead key."""
    import subprocess
    for command in _clipboard_readers():
        try:
            got = subprocess.run(command, capture_output=True, timeout=2)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if got.returncode == 0 and got.stdout:
            return _pasteable(got.stdout)
    return None


# How much of a paste will be taken, and the characters kept. Pasting an image
# the clipboard is holding meant binary noise landing in a note.
PASTE_LIMIT = 4000

CLIPBOARD_HINT = ("Nothing on the clipboard to paste - tdash reads it with "
                  "xclip, xsel, wl-paste or pbpaste, whichever this session "
                  "has")


def _pasteable(raw):
    """Decoded clipboard text, or None if it is not text at all.

    NUL and the other control characters are the giveaway: an image on the
    clipboard is not something to be typed into a field."""
    if not raw or b"\x00" in raw:
        return None
    text = raw.decode("utf-8", "replace")[:PASTE_LIMIT]
    kept = "".join(c for c in text
                   if c == "\n" or c == "\t" or c.isprintable() or c == " ")
    if not kept.strip():
        return None
    return kept


def _pasted_text(text, inline=False):
    """Clipboard text shaped for the field it goes into.

    Line endings are normalised. A single-line field takes the breaks out
    rather than deleting them - the old code used a character class there and
    silently stripped every newline from everything pasted."""
    if not text:
        return ""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    return out.replace("\n", " ") if inline else out


def copy_to_clipboard(text):
    """Ask the terminal to put this on the clipboard. Returns True if sent."""
    if not text:
        return False
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    write_escape(f"\x1b]52;c;{payload}\x07")
    return True


def _word_start_left(text):
    """Where the word ending a single-line value begins.

    Same rule as ctrl+backspace in a multiline field: take the tail of the word
    the cursor sits in, or the whole of the previous one once past the space."""
    index = len(text)
    if not index:
        return 0
    if not TextBuffer._is_word(text[index - 1]):
        while index > 0 and not TextBuffer._is_word(text[index - 1]):
            index -= 1
    while index > 0 and TextBuffer._is_word(text[index - 1]):
        index -= 1
    return index


def caret():
    """The blinking cursor, or nothing while it is in its off phase."""
    return "▏" if blink_state() else ""


def multiline_block(buffer, top=0, rows=None):
    """The visible window of the field, one row per line.

    A paragraph longer than the screen used to be drawn whole, which pushed the
    prompt off the bottom and left the terminal in a mess. Only the lines that
    fit are drawn, and the window follows the cursor. Markers say when there is
    more above or below."""
    if not buffer.text:
        return caret()
    everything = buffer.lines()
    total = len(everything)
    if rows is None:
        rows = field_rows()
    if total <= rows:
        top = 0
    top = max(0, min(top, max(0, total - rows)))
    window = everything[top:top + rows]
    out = []
    for line, col, sel in window:
        if sel and sel[0] != sel[1]:
            lo, hi = sel
            out.append(f"{as_typed(line[:lo])}[reverse]"
                       f"{as_typed(line[lo:hi])}[/]{as_typed(line[hi:])}")
            continue
        if col is None:
            # A caret belongs to the line the cursor is on and nowhere else.
            # Drawing one per line put a cursor at the end of every row,
            # including the empty ones, which looked like stray output.
            out.append(as_typed(line))
            continue
        col = max(0, min(col, len(line)))
        out.append(f"{as_typed(line[:col])}{caret()}{as_typed(line[col:])}")
    if top > 0:
        out.insert(0, "[dim]… more above[/]")
    if top + len(window) < total:
        out.append("[dim]… more below[/]")
    return "\n".join(out)


def render_input(live, prompt, value, options=None, placeholder=None, message=None,
                 cursor=None, multiline=False, buffer=None, top=0, note=None):
    if multiline:
        # Full screen. The dashboard behind it pushed the prompt out of view on
        # a short terminal, and the keys meant for the field went to it instead.
        # The prompt is the panel's title, and only the title: drawn in the
        # body as well it read twice, once on the border and once under it.
        body = (f"[dim]↵ new line   ctrl+u / ctrl+k cut line   "
                f"ctrl+a all   ctrl+x u undo   ctrl+s save   esc cancel[/]")
        # A field that refuses text says so here; dropped, the limit read as
        # the editor having stopped taking keys.
        if isinstance(note, str) and note:
            body += f"\n[{accent()}]{as_typed(note)}[/]"
        body += f"\n\n{multiline_block(buffer, top, field_rows())}"
        box = Panel(body, title=f"[bold {bright()}]{as_typed(prompt)}[/]",
                    border_style=accent(), height=console.height)
        live.update(box)
        live.refresh()
        return
    if options:
        opts = "   ".join(f"{i + 1}. {as_typed(name)}"
                           for i, name in enumerate(options))
        hint = "[dim]type a number, then ↵ to confirm[/]"
        body = (f"{as_typed(prompt)}\n[{accent()}]{opts}[/]\n{hint}\n\n"
                f"{input_line(value, placeholder)}")
    else:
        body = (f"{as_typed(prompt)}\n\n"
                f"{input_line(value, placeholder)}")
    box = Panel(body, title=f"[bold {bright()}]Input[/]",
                border_style=accent())
    live.update(Group(build_layout(message=message), box))
    live.refresh()


def within_limit(value, extra, limit):
    """(value + extra, refused) with a field's length limit applied.

    An insertion that would cross the limit is cut at it, so a description
    never runs over the line it is meant to be; refused says the cut happened,
    which is what the message line reports."""
    if limit is None:
        return value + extra, False
    room = max(0, limit - len(value))
    if len(extra) <= room:
        return value + extra, False
    return value + extra[:room], True


def short_message(limit):
    """What a field says when it refuses text past its limit."""
    return f"Keep it short - at most {limit} characters"


def _room(buffer, limit):
    """How much more text a buffer can take before hitting its limit.

    Selection counts as gone: typing replaces it, so it is not text the new
    characters would be added to."""
    if limit is None:
        return None
    sel = buffer.selected if buffer.has_selection() else None
    used = len(buffer.text) - (sel[1] - sel[0] if sel else 0)
    return max(0, limit - used)


def inline_prompt(live, prompt, message=None, options=None, placeholder=None,
                  initial="", optional=False, multiline=False, limit=None):
    """Free-text entry, or a numeric choice when `options` is given.

    `placeholder` is shown dimmed behind the cursor until the user types; it is
    only a hint, so the field still starts empty. `initial` seeds the field with
    real, editable text - which is what an edit form needs, otherwise a field
    left alone returns None and cancels the whole form instead of keeping its
    value.

    On Enter a field that is `optional`, or that was `initial` and has been
    emptied, returns "" rather than None. Without that, skipping an optional
    field cancels the whole form instead of leaving it blank - which made OS
    impossible to add at all. Esc cancels either way.

    `multiline` flips the keys, because a field holding a paragraph cannot be
    committed by the same key that breaks its lines: Enter inserts a newline and
    ctrl+s saves. The cursor is real - arrows, Home and End move it - so an
    existing note can be edited rather than retyped from scratch.

    `limit` is a maximum length for the text. A field that has one refuses
    whatever would pass it and says "Keep it short" on the message line; the
    description uses it so one field cannot quietly become a second set of
    notes.
    """
    value = initial
    cursor = len(value)
    is_choice = options is not None
    buffer = TextBuffer(value) if multiline else None
    last_size = console.size
    # Open with the cursor on screen. It starts at the end of whatever was
    # there, so a long description used to open showing the top of the text
    # with the caret nowhere in sight.
    top = scroll_to(cursor_row(buffer), 0, len(buffer.lines()),
                    field_rows()) if multiline else 0
    render_input(live, prompt, value, options=options, placeholder=placeholder,
                 message=message, cursor=cursor, multiline=multiline,
                 buffer=buffer, top=top)
    _was_mouse = mouse_enabled()
    # Hand the mouse back to the terminal for the duration of the field, every
    # kind of field. Mouse reporting is what stops the terminal dragging out a
    # selection, so ctrl+shift+c had nothing to copy - and this only covered the
    # multi-line ones, which left a machine name, a date or an OS just as stuck
    # as before.
    _MOUSE_ON[0] = False
    write_escape(MOUSE_OFF)
    # Ask for pasted text to arrive bracketed, so it lands as one block of text
    # instead of a stream of keys the parser has to guess at.
    write_escape(PASTE_ON)
    try:
        return _prompt_loop(live, prompt, value, options, placeholder, message,
                            cursor, is_choice, multiline, buffer, initial,
                            optional, last_size, top=top, limit=limit)
    finally:
        write_escape(PASTE_OFF)
        _MOUSE_ON[0] = _was_mouse
        if _was_mouse:
            write_escape(MOUSE_ON)


def _prompt_loop(live, prompt, value, options, placeholder, message, cursor,
                 is_choice, multiline, buffer, initial, optional, last_size,
                 top=0, limit=None):
    lit = blink_state()
    # A one-line field gets an edit history too: the text it opened with, and
    # the value before each change after that.
    value_past = [value]
    value_future = []
    value_typing = False
    # What the screen handed the field. A press with nothing to step to says
    # so on the message line; one that does step clears the note again. A
    # silent redraw read as the key doing nothing at all.
    screen_message = message
    # A field over its limit says so until the next key that changes the text.
    # One frame only was not enough: the idle caret-blink redraw came straight
    # after and wiped it, so the refusal was never actually seen.
    note = None
    while True:
        try:
            key = read_key(0.2)
        except Chord as chord:
            # ctrl+x u / r / q are raised by read_key before the field ever
            # sees them, so a field has to catch them to undo itself. Left
            # alone they escaped to the dashboard, which undid the file and
            # threw you back on the menu - the opposite of what was asked
            # for, which was to have the line you just deleted back.
            if chord.token == CHORD_QUIT:
                raise                    # quitting still works from anywhere
            key = chord.token
            if multiline:
                if chord.token == CHORD_UNDO:
                    stepped = buffer.undo()
                    empty = "Nothing to undo"
                else:
                    stepped = buffer.redo()
                    empty = "Nothing to redo"
                message = screen_message if stepped else empty
                note = None
                top = scroll_to(cursor_row(buffer), top,
                                len(buffer.lines()), field_rows())
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=message,
                             cursor=cursor, multiline=True, buffer=buffer,
                             top=top, note=note)
                continue
            stepped = False
            if chord.token == CHORD_UNDO and value_past and value_past[-1] != value:
                value_future.append(value)
                value = value_past.pop()
                stepped = True
            elif chord.token == CHORD_REDO and value_future:
                value_past.append(value)
                value = value_future.pop()
                stepped = True
            # The next keystroke starts a fresh run, not a continuation of
            # the one that was just undone.
            value_typing = False
            message = screen_message if stepped else (
                "Nothing to undo" if chord.token == CHORD_UNDO
                else "Nothing to redo")
            render_input(live, prompt, value, options=options,
                         placeholder=placeholder, message=message,
                         cursor=len(value), multiline=False)
            continue
        if key is None:
            # Idle: this is the tick the caret blinks on. Without the redraw it
            # would sit on screen unchanged, which is what it did before.
            phase = blink_state()
            if phase != lit:
                lit = phase
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=message,
                             cursor=cursor, multiline=multiline, buffer=buffer,
                             top=top, note=note)
            if console.size != last_size:
                last_size = console.size
                if multiline:
                    top = scroll_to(cursor_row(buffer), 0,
                                    len(buffer.lines()), field_rows())
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=message,
                             cursor=cursor, multiline=multiline, buffer=buffer,
                             top=top, note=note)
            continue
        if multiline:
            if key in (KEY_PGDN, KEY_PGUP):
                # Page the window and leave the cursor at the end of the page
                # now on screen. Scrolling the window on its own left the caret
                # stranded somewhere off screen, so the next keystroke yanked the
                # view back and the paging looked like it had done nothing.
                rows = field_rows()
                page = max(1, rows - 1)
                total = len(buffer.lines())
                target = max(0, min(top + (page if key == KEY_PGDN else -page),
                                    max(0, total - rows)))
                top = target
                buffer.clear_selection()
                buffer._goto(min(target + rows - 1, total - 1), 0)
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=message,
                             cursor=cursor, multiline=True, buffer=buffer,
                             top=top, note=note)
                continue
            blink_state(force=True)
            lit = True
            status = multiline_key(buffer, key, limit=limit)
            if status == "cancel":
                return None
            if status == "save":
                return buffer.text if not optional or buffer.text.strip() else ""
            if status == "clipboard":
                # Shown in the field's own message line and then cleared, so it
                # says what went wrong without waiting around over the text.
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=CLIPBOARD_HINT,
                             cursor=cursor, multiline=True, buffer=buffer,
                             top=top, note=note)
                continue
            if status == "limit":
                # The keystroke past the limit changed nothing; say why so it
                # does not read as the editor having stopped accepting keys.
                note = short_message(limit)
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder,
                             note=note,
                             cursor=cursor, multiline=True, buffer=buffer,
                             top=top)
                continue
            # ctrl+x u / r / q are raised as a Chord by read_key and caught at
            # the top of this loop, undoing the text rather than the file. A
            # read_key that hands ctrl+x back as an ordinary key - as anything
            # driving this loop without the terminal behind it does - is
            # answered the same way here.
            if status == "chord":
                follow = read_key(CHORD_WAIT)
                if follow == "u":
                    stepped = buffer.undo()
                    message = screen_message if stepped else "Nothing to undo"
                elif follow == "r":
                    stepped = buffer.redo()
                    message = screen_message if stepped else "Nothing to redo"
                elif follow == "q":
                    return CHORD_PREFIX + follow
            top = scroll_to(cursor_row(buffer), top, len(buffer.lines()),
                            field_rows())
            # The key was taken: whether it made room or added text, the
            # refusal note has said its piece.
            note = None
            render_input(live, prompt, value, options=options,
                         placeholder=placeholder, message=message,
                         cursor=cursor, multiline=True, buffer=buffer, top=top,
                         note=note)
            continue
        if key == CTRL_X:
            # The terminal raises the chord instead of returning ctrl+x, and
            # that is handled at the top of this loop. A driver that hands it
            # back as an ordinary key is answered the same way here.
            follow = read_key(CHORD_WAIT)
            stepped = False
            if follow == "u" and value_past and value_past[-1] != value:
                value_future.append(value)
                value = value_past.pop()
                stepped = True
            elif follow == "r" and value_future:
                value_past.append(value)
                value = value_future.pop()
                stepped = True
            if follow in ("u", "r"):
                message = screen_message if stepped else (
                    "Nothing to undo" if follow == "u" else "Nothing to redo")
            render_input(live, prompt, value, options=options,
                         placeholder=placeholder, message=message,
                         cursor=len(value), multiline=False)
            continue
        if key in ("\x19", "\x1b[99;6u", "\x1b[67;6u"):   # ctrl+y / ctrl+shift+c
            copy_to_clipboard(value)
            continue
        # Everything below changes the value; each key works out what the
        # value becomes before anything is recorded, so a key that changed
        # nothing - a backspace at the start of the line, text refused by the
        # length limit - leaves no undo step that undoes to the same text.
        new = value
        refused = False
        if isinstance(key, Pasted):
            pasted = key.text.replace("\r\n", " ").replace("[\r\n]", " ")
            pasted = pasted.replace("\r", " ").replace("\n", " ").strip()
            if pasted and not (is_choice and not pasted.isdigit()):
                new, refused = within_limit(value, pasted, limit)
        elif key in ("\r", "\n"):
            if is_choice:
                if value.isdigit() and 1 <= int(value) <= len(options):
                    return options[int(value) - 1]
                value = ""
                new = ""
            else:
                value = value.strip()
                if not value and (initial or optional):
                    return ""              # cleared or skipped, not cancelled
                return value or None
        elif key in ("\x17", "\x08"):
            new = value[:_word_start_left(value)]
        elif key == "\x7f":
            new = value[:-1]
        elif key in ("\x1b", "\x03", "\x04"):
            return None
        elif key in (CTRL_V, KEY_PASTE):
            pasted = _pasted_text(clipboard_paste(), inline=True)
            if pasted:
                new, refused = within_limit(value, pasted, limit)
            else:
                render_input(live, prompt, value, options=options,
                             placeholder=placeholder, message=CLIPBOARD_HINT,
                             cursor=len(value), multiline=False)
                continue
        elif (is_choice and key.isdigit()) or (not is_choice and key.isprintable()):
            new, refused = within_limit(value, key, limit)
        else:
            continue
        if new != value:
            # A run of ordinary typing is one step rather than one per
            # letter, so undo takes back a word at a time. Anything new makes
            # the redo stack meaningless again.
            typing = len(key) == 1 and key.isprintable() and not key.isspace()
            if not (typing and value_typing) and (not value_past
                                                  or value_past[-1] != value):
                value_past.append(value)
            value_typing = typing
            value_future.clear()
            value = new
        # The hint is for this keystroke only: the next character that fits
        # takes it away again, so it never sits there over the text.
        note = short_message(limit) if refused else message
        render_input(live, prompt, value, options=options, placeholder=placeholder,
                     message=note, cursor=len(value), multiline=multiline)


class TextBuffer:
    """The text being edited, with a cursor and an optional selection.

    A selection is an anchor index; while it is set everything between the
    anchor and the cursor is highlighted and typing replaces it, which is what
    ctrl+a has to mean for "select all" to be useful rather than decorative.
    """

    def __init__(self, text=""):
        self.text = text
        self.cursor = len(text)
        self.anchor = None
        # Undo lives here, on the unsaved text, not on the saved data. Sending
        # ctrl+x u out to the dashboard undid the last save instead - so it
        # unwound the editor, threw away what you had typed, and redrew the
        # whole app, when what you wanted was the line you had just deleted.
        # Seeded with the text the field opened with, so undo walks back to
        # where you started and then stops, instead of past it.
        self.past = [(self.text, self.cursor, self.anchor)]
        self.future = []
        self._typing = False     # a run of typing is one undo, not one per key

    # ----------------------------------------------------------------- undo
    def snapshot(self, typing=False):
        """Record the state before a change, so it can be put back.

        A run of ordinary typing is recorded once and then extended, so undo
        takes back a word rather than a single letter; anything else is its
        own step.

        A state identical to the one already on top is not recorded: the field
        opens with its current text on the stack, so the first keystroke used to
        push a second copy of it and the bottom of the undo stack held presses
        that looked like they did nothing."""
        now = (self.text, self.cursor, self.anchor)
        if self.past and self.past[-1] == now:
            self._typing = typing
            return
        if not (self.past and self._typing and typing):
            self.past.append(now)
            # Anything new makes the redo stack meaningless again.
            self.future.clear()
        self._typing = typing

    def undo(self):
        """Step back one change. False when there is nothing to step back to."""
        self._typing = False
        # Compared against the text as it stands, not counted: a field opens
        # with its current text already on the stack, so a length check treated
        # the opening state as "nothing to undo" and, before that, left a
        # second copy of it on the stack - a press that changed nothing and
        # looked like the key was broken.
        if not self.past or self.past[-1] == (self.text, self.cursor,
                                              self.anchor):
            return False
        self.future.append((self.text, self.cursor, self.anchor))
        self.text, self.cursor, self.anchor = self.past.pop()
        return True

    def redo(self):
        """Step forward again. False when there is nothing to step forward to."""
        self._typing = False
        if not self.future:
            return False
        self.past.append((self.text, self.cursor, self.anchor))
        self.text, self.cursor, self.anchor = self.future.pop()
        return True

    # ------------------------------------------------------------- selection
    @property
    def selected(self):
        if self.anchor is None:
            return None
        return (min(self.anchor, self.cursor), max(self.anchor, self.cursor))

    def has_selection(self):
        sel = self.selected
        return sel is not None and sel[0] != sel[1]

    def select_all(self):
        self.anchor, self.cursor = 0, len(self.text)

    @staticmethod
    def _is_word(char):
        return char.isalnum() or char == "_"

    def _word_left_at(self, index):
        """Where the word to the left of a position begins."""
        while index > 0 and not self._is_word(self.text[index - 1]):
            index -= 1
        while index > 0 and self._is_word(self.text[index - 1]):
            index -= 1
        return index

    def delete_word_left(self):
        """Remove the word to the left of the cursor.

        One word per press, taking the tail of the word the cursor is sitting
        in, or the whole of the previous word once it has moved past the
        whitespace. Running out of words on this line is not the end of it: the
        line break counts as whitespace, so the search carries on into the line
        above and joins it, the way a terminal's ctrl+w does.
        """
        self.delete_selection()
        if not self.cursor:
            return
        start = self.cursor
        if self._is_word(self.text[start - 1]):
            # Inside a word: take only the part before the cursor.
            while start > 0 and self._is_word(self.text[start - 1]):
                start -= 1
        else:
            # On whitespace, a line break or nothing: cross it and take a whole
            # word from whatever is on the left, above this line included.
            while start > 0 and not self._is_word(self.text[start - 1]):
                start -= 1
            while start > 0 and self._is_word(self.text[start - 1]):
                start -= 1
        self.text = self.text[:start] + self.text[self.cursor:]
        self.cursor = start

    def _word_right_at(self, index):
        """Where the word to the right of a position ends."""
        stop = len(self.text)
        while index < stop and not self._is_word(self.text[index]):
            index += 1
        while index < stop and self._is_word(self.text[index]):
            index += 1
        return index

    def word_left(self):
        """ctrl+left - back to the start of the previous word."""
        self.clear_selection()
        self.cursor = self._word_left_at(self.cursor)

    def word_right(self):
        """ctrl+right - forward to the start of the next word."""
        self.clear_selection()
        self.cursor = self._word_right_at(self.cursor)

    def select_word_left(self):
        """ctrl+shift+left - extend the selection a word at a time."""
        if not self.has_selection():
            self.anchor = self.cursor
        self.cursor = self._word_left_at(self.cursor)

    def select_word_right(self):
        """ctrl+shift+right - extend the selection a word at a time."""
        if not self.has_selection():
            self.anchor = self.cursor
        self.cursor = self._word_right_at(self.cursor)

    def select_line_up(self):
        """Extend the selection to the start of the line above.

        The first press anchors where the cursor is and jumps a line; further
        presses keep the anchor and keep climbing."""
        if not self.has_selection():
            self.anchor = self.cursor
        start = self.text.rfind("\n", 0, self.cursor)
        self.cursor = 0 if start < 0 else start

    def select_line_down(self):
        """Extend the selection to the start of the line below."""
        if not self.has_selection():
            self.anchor = self.cursor
        end = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if end < 0 else end + 1

    def selected_text(self):
        """The selected characters, or "" when nothing is selected."""
        if not self.has_selection():
            return ""
        lo, hi = self.selected
        return self.text[lo:hi]

    def clear_selection(self):
        self.anchor = None

    def delete_selection(self):
        if not self.has_selection():
            return
        lo, hi = self.selected
        self.text = self.text[:lo] + self.text[hi:]
        self.cursor = lo
        self.anchor = None

    # --------------------------------------------------------------- editing
    def insert(self, chunk):
        self.delete_selection()
        self.text = self.text[:self.cursor] + chunk + self.text[self.cursor:]
        self.cursor += len(chunk)

    def backspace(self):
        self.delete_selection()
        if self.cursor:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1

    def delete_forward(self):
        self.delete_selection()
        if self.cursor < len(self.text):
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]

    def kill_left(self):
        """ctrl+u - drop everything from the start of the line to the cursor.

        Pressed again at the start of a line it takes the line above as well,
        so it walks backwards a line at a time the way a terminal's kill-line
        does. Without that it went inert after the first press, which is what
        readline's unix-line-discard would never do."""
        self.delete_selection()
        start = self.text.rfind("\n", 0, self.cursor) + 1
        if start == self.cursor and self.cursor > 0:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1
            return
        self.text = self.text[:start] + self.text[self.cursor:]
        self.cursor = start

    def kill_right(self):
        """ctrl+k - drop everything from the cursor to the end of the line.

        Pressed again on a line break it removes that break and joins the next
        line on, so it walks forwards a line at a time."""
        self.delete_selection()
        end = self.text.find("\n", self.cursor)
        if end == self.cursor and end >= 0:
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
            return
        end = len(self.text) if end < 0 else end
        self.text = self.text[:self.cursor] + self.text[end:]

    def newline(self):
        self.insert("\n")

    # --------------------------------------------------------------- motion
    def _pos(self):
        """(line index, column) of the cursor."""
        before = self.text[:self.cursor]
        row = before.count("\n")
        start = before.rfind("\n") + 1
        return row, self.cursor - start

    def _lines(self):
        return self.text.split("\n")

    def _goto(self, row, col):
        lines = self._lines()
        row = max(0, min(row, len(lines) - 1))
        self.cursor = sum(len(l) + 1 for l in lines[:row]) + min(col, len(lines[row]))

    def left(self):
        self.clear_selection()
        self.cursor = max(0, self.cursor - 1)

    def right(self):
        self.clear_selection()
        self.cursor = min(len(self.text), self.cursor + 1)

    def home(self):
        self.clear_selection()
        self.cursor = self.text.rfind("\n", 0, self.cursor) + 1

    def end(self):
        self.clear_selection()
        stop = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if stop < 0 else stop

    def up(self):
        self.clear_selection()
        row, col = self._pos()
        if row:
            self._goto(row - 1, col)

    def down(self):
        self.clear_selection()
        row, col = self._pos()
        if row + 1 < len(self._lines()):
            self._goto(row + 1, col)

    def lines(self):
        """(line, cursor column, selected-from-or-None) per row, for drawing."""
        out, pos = [], 0
        for line in self._lines():
            if pos <= self.cursor <= pos + len(line):
                col = self.cursor - pos
            else:
                col = None
            sel = None
            if self.has_selection():
                lo, hi = self.selected
                if pos + len(line) >= lo and pos <= hi:
                    sel = (max(0, lo - pos), min(len(line), hi - pos))
            out.append((line, col, sel))
            pos += len(line) + 1
        return out


# ctrl+letter codes. The terminal delivers them as plain bytes; IXON has to be
# off or ctrl+s (XOFF) never arrives.
# ctrl+k, not ctrl+r: the redo chord is ctrl+x then the letter r, and
# keeping r out of the editor keys stops the two colliding on screen.
CTRL_U, CTRL_K, CTRL_A, CTRL_S, CTRL_X, CTRL_Q = "\x15", "\x0b", "\x01", "\x13", "\x18", "\x11"
# ctrl+y copies from a field, which is where a terminal's own ctrl+shift+c
# cannot reach: mouse reporting means the terminal has no selection to take.
CTRL_Y = "\x19"
# ctrl+v: the terminal usually claims ctrl+shift+v for itself, so this is the
# one that reaches the program and is otherwise dead. The clipboard has to be
# read by shelling out - see clipboard_paste.
CTRL_V = "\x16"

# ctrl+x u / r / q, returned as CHORD_UNDO etc so any layer that is reading
# keys can hand the command back up to the dashboard. Without this a shortcut
# only worked wherever it happened to be handled.
CHORD_PREFIX = "\x00chord:"
CHORD_UNDO, CHORD_REDO, CHORD_QUIT = (CHORD_PREFIX + "u", CHORD_PREFIX + "r",
                                      CHORD_PREFIX + "q")
CHORDS = (CHORD_UNDO, CHORD_REDO, CHORD_QUIT)

_MOUSE_ON = [True]


def mouse_enabled():
    return _MOUSE_ON[0]


def is_chord(key):
    return isinstance(key, str) and key.startswith(CHORD_PREFIX)


class Chord(Exception):
    """A ctrl+x command raised from wherever the keys happened to be read.

    Raising rather than returning a token means every picker, submenu and
    editor can pass it up without knowing about it, so ctrl+x u / r / q work
    from anywhere on screen instead of only where they were handled."""

    def __init__(self, token):
        super().__init__(token)
        self.token = token


# How long ctrl+x waits for its second key. Half a second is not enough time
# for a person; two is comfortable without leaving a dead ctrl+x hanging.
CHORD_WAIT = 2.0


def read_chord(key, timeout=CHORD_WAIT):
    """Finish a ctrl+x sequence. Raises Chord, or returns None if the key after
    ctrl+x is not one of the commands."""
    if key != CTRL_X:
        return None
    # The second key is a plain letter: ctrl+x u, not ctrl+x ctrl+u.
    follow = read_key(timeout)
    got = {"u": CHORD_UNDO, "r": CHORD_REDO, "q": CHORD_QUIT}.get(follow)
    if got:
        raise Chord(got)
    return None


def multiline_key(buf, key, limit=None):
    """Apply one keystroke to a TextBuffer.

    Returns "cancel" (Esc), "save" (ctrl+s), "limit" (the key would pass the
    field's length limit), or None while typing. The status is separate from
    the buffer because the buffer is always changing.
    """
    # Anything you press brings the caret straight back, the way a terminal's own
    # cursor does; it only fades again after a pause.
    blink_state(force=True)
    if key in (CTRL_Y, KEY_COPY):           # ctrl+y, or ctrl+shift+c
        copy_to_clipboard(buf.selected_text() or buf.text)
        return None
    if isinstance(key, Pasted) or key in (CTRL_V, KEY_PASTE):
        # Pasted text is inserted as-is. Going through it one character at a
        # time would let a paste that contains a newline submit the field, and
        # would make ctrl+u or escape inside the pasted text take effect.
        text = (key.text if isinstance(key, Pasted) else clipboard_paste())
        pasted = _pasted_text(text)
        if not pasted:
            # Nothing to paste, and nothing said: the key looked broken. The
            # usual cause is a terminal with no clipboard tool this app can
            # read, so say which it is looking for.
            return "clipboard"
        room = _room(buf, limit)
        cut = room is not None and len(pasted) > room
        if cut:
            pasted = pasted[:room]
        if not pasted:
            return "limit"
        buf.snapshot()
        buf.insert(pasted)
        return "limit" if cut else None
    if key in ("\x1b", "\x03"):
        return "cancel"
    if key == CTRL_S:
        return "save"
    if key == CTRL_X:
        # read_key raises the chord before this is reached; the marker says
        # "not text" so the caller does not undo it twice.
        return "chord"
    # Only the keys that change the text leave an undo step. Cursor moves and
    # selections used to be recorded too, so the first ctrl+x u undid a step
    # that changed nothing on screen - the key looked asleep. Plain typing is
    # marked so a run of letters is one step, taken back a word at a time.
    typed = len(key) == 1 and key.isprintable()
    if (typed or key in ("\r", "\n")) and _room(buf, limit) == 0:
        return "limit"
    if key in (CTRL_U, CTRL_K, KEY_DELETE_WORD_LEFT, "\x17", "\x08", "\x7f",
               KEY_DELETE) or typed or key in ("\r", "\n"):
        buf.snapshot(typing=typed and not key.isspace())
    if key == CTRL_U:
        buf.kill_left()
    elif key == CTRL_K:
        buf.kill_right()
    elif key == CTRL_A:
        buf.select_all()
    elif key in ("\r", "\n"):
        buf.newline()
    elif key in (KEY_DELETE_WORD_LEFT, "\x17", "\x08"):
        # ^H is what a terminal sends for ctrl+backspace on Linux, and there is
        # no way to tell it apart from a backspace key configured to send ^H -
        # but ^H is rare for plain backspace and ctrl+backspace is the one
        # people reach for. ctrl+w and alt+backspace always work regardless.
        buf.delete_word_left()
    elif key == "\x7f":
        buf.backspace()
    elif key == KEY_DELETE:
        buf.delete_forward()
    elif key == KEY_SELECT_WORD_LEFT:
        buf.select_word_left()
    elif key == KEY_SELECT_WORD_RIGHT:
        buf.select_word_right()
    elif key == KEY_WORD_LEFT:
        buf.word_left()
    elif key == KEY_WORD_RIGHT:
        buf.word_right()
    elif key == KEY_SELECT_UP:
        buf.select_line_up()
    elif key == KEY_SELECT_DOWN:
        buf.select_line_down()
    elif key == KEY_LEFT:
        buf.left()
    elif key == KEY_RIGHT:
        buf.right()
    elif key == KEY_HOME:
        buf.home()
    elif key == KEY_END:
        buf.end()
    elif key == KEY_UP:
        buf.up()
    elif key == KEY_DOWN:
        buf.down()
    elif key.isprintable():
        buf.insert(key)
    return None


def render_list(live, prompt, names, rows, cur, top, view, message=None,
                hint=None, marks=None):
    lines = []
    for r in range(top, min(top + view, len(rows))):
        kind = rows[r][0]
        if kind == "h":
            lines.append(f"[bold {accent()}]── {as_typed(rows[r][1])} ──[/]")
            continue
        _, index, number = rows[r]
        text = (as_typed(names[index]) if number is None
                else f"{number:>2}. {as_typed(names[index])}")
        if marks:
            # marks is a list of booleans in the same order as the items, so
            # the row's own index says whether it is marked. A callable is
            # called on every draw, so a mark made since the list opened shows
            # up without reopening it.
            marked = marks[index] if isinstance(marks, list) else bool(
                marks(index))
            text = f"\u2713 {text}" if marked else f"  {text}"
        lines.append(f"[bold {accent()}]▸[/] [reverse]{text}[/]" if r == cur else f"  {text}")
    here = sum(1 for row in rows[:cur] if row[0] == "i") + 1
    total = sum(1 for row in rows if row[0] == "i")
    # A hint is the whole key line for this list. Laying the generic line out
    # underneath it repeated every key it already said - "↑/↓ move  ↵ select"
    # under a hint that began "↑↓ move  ↵ read" - which read as the app not
    # knowing which was current. So: hint, or generic, never both.
    if hint:
        footer = f"[bold {accent()}]{hint}[/]  [dim]({here}/{total})[/]"
    else:
        # Same shape as a screen that brings its own hint: the key, then what
        # it does in brackets, so a list with and without extra keys are read
        # the same way.
        footer = (f"[dim]↑↓ move  ↵ (Select)  1-9 (Jump)  esc (Cancel)  "
                  f"({here}/{total})[/]")
    box = Panel(
        Group("\n".join(lines), "", footer),
        title=f"[bold {bright()}]{prompt}[/]",
        border_style=accent(),
    )
    live.update(_list_body(message, box, view))
    live.refresh()


# Below this the full dashboard plus a picker no longer fits, and the picker is
# what the person came for.
_TIGHT_SCREEN = 30


def _list_body(message, box, view):
    """The dashboard with the picker under it, never cropped.

    On a short terminal the full dashboard filled the screen on its own, so the
    list was pushed off the bottom and a six-entry submenu showed a single row.
    Shrinking the dashboard, and dropping it if even that is not enough, keeps
    the list readable.
    """
    if console.height >= _TIGHT_SCREEN:
        return Group(build_layout(message=message), box)
    from ui import window_screen          # local: ui imports this module
    for compact in (False, True, "none"):
        head = [] if compact == "none" else [build_layout(message=message,
                                                          compact=compact)]
        body = Group(*head, box)
        if not window_screen(body, 0)[2]:   # 0 == it already fits
            return body
    return Group(box)


# Terminals disagree on Shift+Enter. Most send a plain "\r", identical to
# Enter, so there is nothing to tell apart. Some send ESC then CR/LF, which is
# this token. The kitty keyboard protocol would report it properly, but turning
# it on also changes how Ctrl+C and Escape arrive, and this app relies on both
# for quitting and going back - a poor trade for one key.
SHIFT_ENTER = "\x00shift-enter"


def inline_list(live, prompt, items, message=None, hint=None,
                shortcuts=None, max_rows=None, refresh=None, ticks=None,
                start=None, chords=None):
    """Scrollable arrow-key picker. Accepts [str] or [(group, name)].

    `shortcuts` maps a single key to an action run against the highlighted row:
    mark, add, edit, delete. The action returns the message to show and the list
    stays open, so the whole screen can be worked from one place instead of
    walking into a submenu for each of them and coming back.

    `ticks` says which items are marked - a list of booleans in the order they
    were given, or a callable returning one. Marked rows carry the same tick
    the machines list puts on a finished box, so "this one is on" reads the
    same way everywhere.

    `refresh` re-reads the items after a shortcut. Without it the rows kept the
    labels they were built with, so marking a machine left the row reading
    "Networked" with no tick on it until you left the list and came back.

    `chords` is handed a ctrl+x token and returns the message to show, the way
    a shortcut does. Without it a chord travelled all the way to the dashboard
    loop, which ran the command and rebuilt the main menu under the person - so
    undoing a mark looked like the list had restarted the app.
    """
    shortcuts = shortcuts or {}
    max_rows = max_rows or LIST_MAX
    if not items:
        return None
    names, rows = prepare_rows(items)
    row_of = [r for r, row in enumerate(rows) if row[0] == "i"]
    # A screen that reopens its list after every change would otherwise drop
    # the cursor back at the top each time, so marking two things in a row
    # meant walking past the same rows twice.
    cur = row_of[min(start, len(row_of) - 1)] if start else row_of[0]
    top, view = 0, list_view(max_rows)
    last_size = console.size
    marks = ticks() if callable(ticks) else ticks
    render_list(live, prompt, names, rows, cur, top, view, message=message,
                hint=hint, marks=marks)
    while True:
        try:
            key = read_key(0.2)
        except Chord as chord:
            if chords is None:
                raise
            said = chords(chord.token)
            if isinstance(said, str):
                message = said
            # The same re-read the shortcut path does: an undo can change a
            # row's tick or labels, and the list has to show that at once.
            if refresh is not None:
                items = refresh()
                names, rows = prepare_rows(items)
                row_of = [r for r, row in enumerate(rows) if row[0] == "i"]
                cur = cur if cur in row_of else (row_of[0] if row_of else 0)
                top = fit_top(cur, top, len(rows), view)
            render_list(live, prompt, names, rows, cur, top, view,
                        message=message, hint=hint,
                        marks=ticks() if callable(ticks) else ticks)
            continue
        if key is None:
            if console.size != last_size:
                last_size = console.size
                view = list_view(max_rows)
                render_list(live, prompt, names, rows, cur, top, view,
                            message=message, hint=hint,
                            marks=ticks() if callable(ticks) else ticks)
            continue
        if shortcuts and key in shortcuts:
            row = rows[cur]
            what = names[row[1]] if row[0] == "i" else row[1]
            said = shortcuts[key](live, what)
            # Only something displayable counts as a message. An action that
            # was cancelled returns a sentinel - pressing Esc in the Add form
            # does exactly that - and handing that to the renderer tore the
            # whole program down with a TypeError.
            message = said if isinstance(said, str) else None
            # Re-read the rows so a mark shows its tick at once. The cursor
            # stays on the same line: marking changes a row's text, not the
            # number of rows.
            if refresh is not None:
                items = refresh()
                names, rows = prepare_rows(items)
                row_of = [r for r, row in enumerate(rows) if row[0] == "i"]
                cur = cur if cur in row_of else (row_of[0] if row_of else 0)
                top = fit_top(cur, top, len(rows), view)
            render_list(live, prompt, names, rows, cur, top, view,
                        message=message, hint=hint,
                        marks=ticks() if callable(ticks) else ticks)
            continue
        if key == KEY_COPY:
            # ctrl+shift+c copies the highlighted row, which is the selection
            # this program knows about. A terminal that claims the key copies
            # its own selection instead, which is what most of them do.
            row = rows[cur]
            what = names[row[1]] if row[0] == "i" else row[1]
            copy_to_clipboard(what)
            message = f"Copied: {what}"
            render_list(live, prompt, names, rows, cur, top, view,
                        message=message, hint=hint,
                        marks=ticks() if callable(ticks) else ticks)
            continue
        if key == KEY_DOWN:
            cur = step_row(rows, cur, 1)
        elif key == KEY_UP:
            cur = step_row(rows, cur, -1)
        elif key == KEY_WHEEL_DOWN:
            cur = step_row(rows, cur, 3)
        elif key == KEY_WHEEL_UP:
            cur = step_row(rows, cur, -3)
        elif key == KEY_PGDN:
            cur = row_of[min(row_of.index(cur) + view, len(row_of) - 1)]
        elif key == KEY_PGUP:
            cur = row_of[max(row_of.index(cur) - view, 0)]
        elif key == KEY_END:
            cur = row_of[-1]
        elif key == KEY_HOME:
            cur = row_of[0]
        elif key in ("\r", "\n"):
            return names[rows[cur][1]]
        elif key in ("\x1b", "\x03", "\x04"):
            return None
        elif key.isdigit() and 1 <= int(key) <= len(row_of):
            cur = row_of[int(key) - 1]
        else:
            continue
        top = fit_top(cur, top, len(rows), view)
        render_list(live, prompt, names, rows, cur, top, view, message=message,
                    hint=hint,
                    marks=ticks() if callable(ticks) else ticks)


def wait_for_key(chords=None):
    """Block until a plain key is pressed, for panels that stay up until they
    are dismissed.

    read_key returns None when its timeout expires, so this must wait while the
    result is None. Getting that backwards makes the panel close by itself.

    A chord does not dismiss the panel: with a `chords` handler it is run in
    place and the handler's message comes back so the caller can redraw and
    keep waiting. Letting it travel to the dashboard rebuilt the main menu, so
    undo from a panel closed it and dumped the reader on the menu."""
    while True:
        try:
            if read_key(0.2) is not None:
                return None
        except Chord as chord:
            if chords is None:
                raise
            return chords(chord.token)


def show_details(live, title, body, note=None, message=None, chords=None):
    """Show a detail panel until a key is pressed.

    ctrl+x u / r keep the panel up: the command runs through `chords` and the
    panel redraws with what it said, instead of the chord escaping and
    rebuilding the dashboard under the reader."""
    while True:
        live.update(Group(
            build_layout(message=message),
            detail_panel(title, body, note),
            "[dim]Press any key to return…[/]",
        ))
        live.refresh()
        said = wait_for_key(chords)
        if said is None:
            return
        if isinstance(said, str):
            message = said
    wait_for_key()