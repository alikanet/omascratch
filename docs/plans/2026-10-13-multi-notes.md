# Multiple Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Omascratch single scratchpad into a keyboard-driven list of standing notes, each in its own file.

**Architecture:** A new Python helper (`omascratch-notes.py`) owns everything that touches the notes folder as a whole (list, delete, migrate) and is unit tested. `Panel.qml` gains a list screen and points its existing atomic autosave at whichever note is open; reads of a single note keep going through the existing `safeRead` reader. Custom titles live in `titles.json`, the sort choice in the existing `settings.json`.

**Tech Stack:** QML on Quickshell (Omarchy shell plugin), Python 3.14 standard library, `unittest`.

**Spec:** `docs/specs/2026-10-13-multi-notes-design.md` (read it before starting; this plan implements it).

## Global Constraints

- Repo: `~/Code/omascratch`, branch `multi-notes`. Commit after every task. Push the branch at the end only. Never push `main`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- No em dashes anywhere you write: UI strings, README, comments, commit messages.
- `Panel.qml` stays one file (it is the plugin entry point; keep the existing pattern, no sibling QML components).
- Colours come only from what `Panel.qml` already uses (`root.foreground`, `root.background`, `Color.accent`, `Color.urgent`, `Style.selectionFillFor(...)`, `Qt.darker(root.foreground, ...)`). No new hues.
- Never read a file with `FileView.text()`. Disk reads go through the existing `safeRead` reader or the helper. FileViews keep `blockAllReads: true`.
- The helper is always run as `python3 -I <helper> ...`.
- Note ids match `^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$` and are checked wherever they are read (helper, list JSON, titles JSON).
- Reads that fail must never fill the editor or overwrite a file (the existing rule in `Panel.qml`).
- Comment style: match `Panel.qml`, whose comments explain *why* in full sentences. Don't add comments that restate the code.

### Live check recipe (used by Tasks 2 to 6)

The panel can only be tested in the running shell. `wtype` and `grim` are installed, so the checks can be driven from a terminal. **Tell the user before driving the desktop**, since keystrokes go to whatever has focus.

```bash
QA=${CLAUDE_JOB_DIR:-/tmp}/tmp/qa; mkdir -p "$QA"
omarchy-restart-shell                     # reload the shell (picks up Panel.qml changes)
sleep 3
journalctl --user -t omarchy-shell --since "-1min" --no-pager | grep -i -E 'omascratch|Panel.qml' # must print no errors
omarchy-shell shell toggle io.github.weedwhitesandwine.omascratch   # open / close the panel
wtype -k Down                             # a plain key
wtype -k Return
wtype -M ctrl n -m ctrl                   # Ctrl+N (same shape for s, d, t, comma)
wtype -M ctrl -k Return -m ctrl           # Ctrl+Enter
wtype 'some text'                         # typing
wtype -k Escape
grim "$QA/step.png"                       # screenshot, then view it with the Read tool
```

State lives in `~/.local/state/omarchy/omascratch/`. Inspect it with `ls -la`, `cat`, and `python3 -I ~/Code/omascratch/omascratch-notes.py list ~/.local/state/omarchy/omascratch`.

## Review Focus

1. Holding Ctrl between two Ctrl+D presses (or releasing and re-pressing Ctrl) must not disarm delete: bare modifier key events have to be ignored by the list key handler. (Task 5, step 4.)
2. If `titles.json` fails to read, or the notes list has not loaded, a later Ctrl+T must not rewrite `titles.json` and wipe the other titles. (Task 4, step 5.)
3. A new note that gets a Ctrl+T title but no body text is still a note, and must not be discarded as blank. (Task 4, step 5.)
4. Typing and then clicking outside the panel within 400 ms (the focus grab closes it) must still save what was typed. (Task 2, step 9.)
5. Greek titles (the user writes Greek) sort sensibly in A to Z: case-insensitive and locale-aware, so `άλφα` sits with `αλφα`, not after `ω`. (Task 3, step 4.)

---

### Task 1: Notes folder helper

**Files:**
- Create: `omascratch-notes.py`
- Test: `tests/test_notes_helper.py`

**Interfaces:**
- Consumes: nothing.
- Produces (CLI, used by `Panel.qml` in Tasks 2 and 5):
  - `python3 -I omascratch-notes.py list <stateDir>`: exit 0, stdout is a JSON array of `{"id": str, "mtime": int (ms since epoch), "firstLine": str}` in no particular order.
  - `python3 -I omascratch-notes.py delete <stateDir> <id>`: exit 0 moved to `trash/`, 2 note not found, 1 refused or failed.
  - `python3 -I omascratch-notes.py migrate <stateDir>`: exit 0 always on success (including "nothing to do"), 1 on I/O failure.
  - Bad arguments: exit 64.
- Produces (Python, for tests): `valid_id(s) -> bool`, `new_id() -> str`, `first_line(raw: bytes) -> str`, `list_notes(state_dir) -> list[dict]`, `delete_note(state_dir, nid) -> int`, `migrate(state_dir) -> int`, `main(argv) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notes_helper.py`:

```python
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("notes_helper", ROOT / "omascratch-notes.py")
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)

ID_A = "20261013-101500-a1b2"
ID_B = "20261013-101600-c3d4"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = self._tmp.name
        self.notes = os.path.join(self.state, "notes")
        self.trash = os.path.join(self.state, "trash")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, data, mtime=None):
        path = os.path.join(self.state, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def read(self, rel):
        with open(os.path.join(self.state, rel), "rb") as handle:
            return handle.read()


class TestValidId(unittest.TestCase):
    def test_accepts_well_formed(self):
        self.assertTrue(helper.valid_id(ID_A))

    def test_rejects_malformed(self):
        for bad in ["", "../x", "20261013-101500-A1B2", "20261013-101500-a1b",
                    ID_A + ".txt", "x" * 20, None, 5]:
            self.assertFalse(helper.valid_id(bad), repr(bad))

    def test_new_id_is_valid(self):
        self.assertTrue(helper.valid_id(helper.new_id()))


class TestFirstLine(unittest.TestCase):
    def test_cases(self):
        cases = {
            b"": "",
            b"\n\n  hello world  \nmore": "hello world",
            b"no newline": "no newline",
            b"   \n\t\n": "",
            b"\r\nwin\r\n": "win",
            b"\xffok": "�ok",
            "Γειά σου\nκόσμε".encode("utf-8"): "Γειά σου",
        }
        for raw, expected in cases.items():
            self.assertEqual(helper.first_line(raw), expected, repr(raw))


class TestListNotes(Base):
    def test_missing_folder_is_empty(self):
        self.assertEqual(helper.list_notes(self.state), [])

    def test_lists_valid_notes(self):
        self.write(f"notes/{ID_A}.txt", "first\nsecond", mtime=1000)
        self.write(f"notes/{ID_B}.txt", "", mtime=2000)
        got = sorted(helper.list_notes(self.state), key=lambda n: n["id"])
        self.assertEqual(got, [
            {"id": ID_A, "mtime": 1000000, "firstLine": "first"},
            {"id": ID_B, "mtime": 2000000, "firstLine": ""},
        ])

    def test_ignores_bad_names(self):
        for name in ["notes.txt", "README", f"{ID_A}.md", f"{ID_A}.txt.tmp", ".hidden.txt"]:
            self.write(f"notes/{name}", "x")
        self.assertEqual(helper.list_notes(self.state), [])

    def test_ignores_symlink(self):
        target = self.write("outside.txt", "secret")
        os.makedirs(self.notes)
        os.symlink(target, os.path.join(self.notes, f"{ID_A}.txt"))
        self.assertEqual(helper.list_notes(self.state), [])

    def test_ignores_directory(self):
        os.makedirs(os.path.join(self.notes, f"{ID_A}.txt"))
        self.assertEqual(helper.list_notes(self.state), [])

    def test_reads_only_the_head(self):
        self.write(f"notes/{ID_A}.txt", "x" * 10000)
        self.assertEqual(len(helper.list_notes(self.state)[0]["firstLine"]), 4096)

    def test_main_prints_json(self):
        self.write(f"notes/{ID_A}.txt", "hi")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = helper.main(["omascratch-notes.py", "list", self.state])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), helper.list_notes(self.state))


class TestDelete(Base):
    def test_moves_to_trash(self):
        self.write(f"notes/{ID_A}.txt", "bye")
        self.assertEqual(helper.delete_note(self.state, ID_A), 0)
        self.assertFalse(os.path.exists(os.path.join(self.notes, f"{ID_A}.txt")))
        self.assertEqual(self.read(f"trash/{ID_A}.txt"), b"bye")

    def test_rejects_bad_id(self):
        self.assertEqual(helper.delete_note(self.state, "../../etc/passwd"), 1)

    def test_missing_note(self):
        os.makedirs(self.notes)
        self.assertEqual(helper.delete_note(self.state, ID_A), 2)

    def test_keeps_earlier_trash(self):
        self.write(f"trash/{ID_A}.txt", "old")
        self.write(f"notes/{ID_A}.txt", "new")
        self.assertEqual(helper.delete_note(self.state, ID_A), 0)
        self.assertEqual(self.read(f"trash/{ID_A}.txt"), b"old")
        self.assertEqual(len(os.listdir(self.trash)), 2)

    def test_refuses_symlink(self):
        target = self.write("outside.txt", "keep me")
        os.makedirs(self.notes)
        os.symlink(target, os.path.join(self.notes, f"{ID_A}.txt"))
        self.assertEqual(helper.delete_note(self.state, ID_A), 1)
        self.assertEqual(self.read("outside.txt"), b"keep me")


class TestMigrate(Base):
    def notes_files(self):
        return sorted(os.listdir(self.notes))

    def test_fresh_install(self):
        self.assertEqual(helper.migrate(self.state), 0)
        self.assertEqual(self.notes_files(), [])

    def test_moves_existing_note(self):
        self.write("notes.txt", "my scratch\n")
        self.assertEqual(helper.migrate(self.state), 0)
        files = self.notes_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(helper.valid_id(files[0][:-4]))
        self.assertEqual(self.read(f"notes/{files[0]}"), b"my scratch\n")
        self.assertFalse(os.path.exists(os.path.join(self.state, "notes.txt")))
        self.assertEqual(self.read("notes.txt.bak"), b"my scratch\n")

    def test_blank_note_left_alone(self):
        self.write("notes.txt", "  \n")
        self.assertEqual(helper.migrate(self.state), 0)
        self.assertEqual(self.notes_files(), [])
        self.assertTrue(os.path.exists(os.path.join(self.state, "notes.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "notes.txt.bak")))

    def test_runs_once(self):
        self.write("notes.txt", "x")
        helper.migrate(self.state)
        helper.migrate(self.state)
        self.assertEqual(len(self.notes_files()), 1)

    def test_existing_folder_still_takes_old_note(self):
        self.write(f"notes/{ID_B}.txt", "already here")
        self.write("notes.txt", "old")
        helper.migrate(self.state)
        self.assertEqual(len(self.notes_files()), 2)

    def test_keeps_earlier_backup(self):
        self.write("notes.txt.bak", "older")
        self.write("notes.txt", "newer")
        helper.migrate(self.state)
        self.assertEqual(self.read("notes.txt.bak"), b"older")
        baks = [n for n in os.listdir(self.state) if n.startswith("notes.txt.bak")]
        self.assertEqual(len(baks), 2)

    def test_oversized_left_alone(self):
        self.write("notes.txt", b"x" * (4 * 1024 * 1024 + 1))
        self.assertEqual(helper.migrate(self.state), 0)
        self.assertEqual(self.notes_files(), [])
        self.assertTrue(os.path.exists(os.path.join(self.state, "notes.txt")))


class TestMain(Base):
    def test_bad_arguments(self):
        for argv in [["h"], ["h", "list"], ["h", "nope", self.state],
                     ["h", "delete", self.state], ["h", "list", self.state, "extra"]]:
            self.assertEqual(helper.main(argv), 64, argv)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd ~/Code/omascratch && python3 -I -m unittest discover -s tests -v`
Expected: ERROR, `FileNotFoundError` for `omascratch-notes.py`.

- [ ] **Step 3: Write the helper**

Create `omascratch-notes.py` and `chmod +x` it:

```python
#!/usr/bin/env python3
"""Everything Omascratch does to its notes folder as a whole.

The panel reads and writes one open note itself. Listing every note, moving
one to the trash and the one-time move from the old single notes.txt live
here, where they can be tested, and where a stray file in the folder is
judged by the same rules every time: a note is a regular file, not a link,
named <id>.txt with an id this script would have made.
"""
import json
import os
import re
import secrets
import stat
import sys
import time

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
FIRST_LINE_BYTES = 4096
NOTE_CEILING = 4 * 1024 * 1024
USAGE = 64


def valid_id(value):
    return isinstance(value, str) and ID_RE.match(value) is not None


def new_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def read_head(path, limit):
    """(bytes, mtime) of at most `limit` bytes, or (None, None) if the path is
    not a regular file of our own. O_NONBLOCK keeps a fifo from hanging us."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, None
        with os.fdopen(fd, "rb") as handle:
            fd = None
            return handle.read(limit), info.st_mtime
    except OSError:
        return None, None
    finally:
        if fd is not None:
            os.close(fd)


def first_line(raw):
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.strip():
            return line.strip()
    return ""


def list_notes(state_dir):
    notes_dir = os.path.join(state_dir, "notes")
    try:
        names = os.listdir(notes_dir)
    except OSError:
        return []
    found = []
    for name in names:
        if not name.endswith(".txt") or not valid_id(name[:-4]):
            continue
        raw, mtime = read_head(os.path.join(notes_dir, name), FIRST_LINE_BYTES)
        if raw is None:
            continue
        found.append({"id": name[:-4], "mtime": int(mtime * 1000), "firstLine": first_line(raw)})
    return found


def free_name(path):
    """`path` if nothing is there, else the same name with a numbered suffix,
    so a move never lands on an earlier file and replaces it."""
    if not os.path.lexists(path):
        return path
    n = 1
    while os.path.lexists(f"{path}.{n}"):
        n += 1
    return f"{path}.{n}"


def delete_note(state_dir, nid):
    if not valid_id(nid):
        return 1
    src = os.path.join(state_dir, "notes", nid + ".txt")
    try:
        if not stat.S_ISREG(os.lstat(src).st_mode):
            return 1
    except FileNotFoundError:
        return 2
    except OSError:
        return 1
    trash = os.path.join(state_dir, "trash")
    try:
        os.makedirs(trash, exist_ok=True)
        os.rename(src, free_name(os.path.join(trash, nid + ".txt")))
    except OSError:
        return 1
    return 0


def migrate(state_dir):
    """Create the notes folder, and bring the old single note into it once.

    The old file is renamed rather than removed, and only after its copy is
    safely written, so a failure part way leaves it where it was and the next
    start simply tries again."""
    notes_dir = os.path.join(state_dir, "notes")
    old = os.path.join(state_dir, "notes.txt")
    try:
        os.makedirs(notes_dir, exist_ok=True)
        raw, _ = read_head(old, NOTE_CEILING + 1)
        if raw is None or len(raw) > NOTE_CEILING or not raw.strip():
            return 0
        dst = os.path.join(notes_dir, new_id() + ".txt")
        tmp = dst + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(tmp, dst)
        os.rename(old, free_name(old + ".bak"))
    except OSError:
        return 1
    return 0


def main(argv):
    if len(argv) == 3 and argv[1] == "list":
        json.dump(list_notes(argv[2]), sys.stdout, ensure_ascii=False)
        return 0
    if len(argv) == 4 and argv[1] == "delete":
        return delete_note(argv[2], argv[3])
    if len(argv) == 3 and argv[1] == "migrate":
        return migrate(argv[2])
    print("usage: omascratch-notes.py list|migrate <stateDir> | delete <stateDir> <id>", file=sys.stderr)
    return USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Note `test_keeps_earlier_backup` expects two `notes.txt.bak*` files: `free_name` gives `notes.txt.bak.1`, which starts with `notes.txt.bak`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd ~/Code/omascratch && python3 -I -m unittest discover -s tests -v`
Expected: all tests PASS (about 25).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/omascratch
git add omascratch-notes.py tests/test_notes_helper.py
git commit -m "Add the notes folder helper: list, delete, migrate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: List screen, open, new note, per-note autosave

The core loop: the panel opens on a list, Up/Down/Enter open a note, Ctrl+N starts one, Ctrl+Enter saves and returns, Esc closes. Sorting is fixed at latest first in this task (Task 3 adds the cycle).

**Files:**
- Modify: `Panel.qml`
- Live install: `~/.config/omarchy/plugins/io.github.weedwhitesandwine.omascratch` (becomes a symlink)

**Interfaces:**
- Consumes: helper CLI `list` and `migrate` from Task 1.
- Produces (used by Tasks 3 to 5, keep these names exact):
  - Properties: `view` ("list" | "edit"), `notes` (array of `{id, mtime, firstLine}`), `notesLoaded` (bool), `listIndex` (int), `listError` (string), `currentId` (string), `currentIsNew` (bool), `dirtySinceOpen` (bool), `loadingNote` (bool), `readingId` (string), `listPending` (string), `idPattern` (RegExp), `notesDir`, `helperPath`, `currentPath`, `sortedNotes` (array).
  - Functions: `focusView()`, `showList()`, `refreshList()`, `loadList(json)`, `moveHighlight(step)`, `openHighlighted()`, `openNote(id)`, `newNote()`, `startEditing(id, text, isNew)`, `writeCurrent()`, `flushSave()`, `finishEditing()`, `firstLineOf(text) -> string`, `sortNotes(list) -> array`, `displayTitle(n) -> string`, `ago(ms) -> string`, `isCtrl(event, key) -> bool`, `handleListKey(event)`.
  - Items: `notesList` (ListView), `headerTitle` (Text), `textArea` (existing).

- [ ] **Step 1: Point the live plugin at the fork**

Tell the user this swaps the live plugin for the fork (it is identical to what is installed until Step 3 lands). Then:

```bash
P=~/.config/omarchy/plugins/io.github.weedwhitesandwine.omascratch
mv "$P" ~/.local/share/omascratch-upstream-backup
ln -s ~/Code/omascratch "$P"
omarchy plugin list | grep -i omascratch
```

Expected: omascratch listed and enabled. If it is missing, the loader does not follow symlinks: remove the link and use a copy instead, re-run after every change:

```bash
rm "$P" && mkdir "$P" && rsync -a --delete --exclude .git ~/Code/omascratch/ "$P"/
```

Back up the current state too, so QA can never cost the user a note: `cp -a ~/.local/state/omarchy/omascratch ~/.local/share/omascratch-state-backup-20261013`.

- [ ] **Step 2: Note the baseline**

Run the live check recipe: restart the shell, open the panel, `grim "$QA/baseline.png"`. Expected: today's single scratchpad, with no errors in the journal.

- [ ] **Step 3: Replace the single-note paths with the per-note state**

In `Panel.qml`, replace:

```qml
  readonly property string notesPath: stateDir + "/notes.txt"
  readonly property string settingsPath: stateDir + "/settings.json"
```

with:

```qml
  readonly property string notesDir: stateDir + "/notes"
  readonly property string settingsPath: stateDir + "/settings.json"
  readonly property string helperPath: pluginDir + "/omascratch-notes.py"

  // "list" or "edit". The settings view sits over either one and returns to it.
  property string view: "list"
  // What the helper last reported, [{id, mtime, firstLine}] in disk order.
  // notesLoaded stays false until one listing has succeeded, so nothing that
  // prunes by this list can mistake "not read yet" for "there are no notes".
  property var notes: []
  property bool notesLoaded: false
  property string listPending: ""
  property int listIndex: 0
  property string listError: ""
  // The note on the edit screen. A new note has an id but no file until it
  // first holds text, so one that is left blank leaves nothing behind.
  property string currentId: ""
  property bool currentIsNew: false
  property bool dirtySinceOpen: false
  // Set while the editor is filled from disk, so the fill is not mistaken
  // for typing and written straight back.
  property bool loadingNote: false
  property string readingId: ""
  readonly property var idPattern: /^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$/
  readonly property string currentPath: root.currentId === "" ? "" : root.notesDir + "/" + root.currentId + ".txt"
  readonly property var sortedNotes: root.sortNotes(root.notes)
```

- [ ] **Step 4: Open on the list, and save on every way out**

Replace:

```qml
  function open(payloadJson) {
    root.opened = true
    root.settingsOpen = false
    root.stayOnTop = false
    Qt.callLater(function() { textArea.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    root.recording = false
  }

  function dismiss() {
    root.opened = false
```

with:

```qml
  function open(payloadJson) {
    root.opened = true
    root.settingsOpen = false
    root.stayOnTop = false
    root.showList()
  }

  // Every way the panel closes passes through here or dismiss(), including
  // a click elsewhere clearing the focus grab, so a save still waiting on
  // its timer is written now rather than lost with the closed panel.
  function close() {
    root.flushSave()
    root.opened = false
    root.recording = false
  }

  function dismiss() {
    root.flushSave()
    root.opened = false
```

Replace:

```qml
  function closeSettings() {
    root.settingsOpen = false
    root.recording = false
    Qt.callLater(function() { textArea.forceActiveFocus() })
  }
```

with:

```qml
  function closeSettings() {
    root.settingsOpen = false
    root.recording = false
    root.focusView()
  }
```

- [ ] **Step 5: Add the list and editing functions**

Replace:

```qml
  function isSettingsShortcut(event) {
    return event.key === Qt.Key_Comma && (event.modifiers & Qt.ControlModifier)
  }
```

with:

```qml
  function isSettingsShortcut(event) {
    return event.key === Qt.Key_Comma && (event.modifiers & Qt.ControlModifier)
  }

  function isCtrl(event, key) {
    return event.key === key && (event.modifiers & Qt.ControlModifier)
  }

  function isEnter(event) {
    return event.key === Qt.Key_Return || event.key === Qt.Key_Enter
  }

  function focusView() {
    Qt.callLater(function() {
      if (root.view === "edit") textArea.forceActiveFocus()
      else notesList.forceActiveFocus()
    })
  }

  function showList() {
    root.view = "list"
    root.listIndex = 0
    root.listError = ""
    root.refreshList()
    root.focusView()
  }

  function refreshList() { listProc.running = false; listProc.running = true }

  // The helper is ours, but its answer is still checked: an id from here
  // becomes a path the editor writes to.
  function loadList(json) {
    var parsed
    try { parsed = JSON.parse(json || "[]") } catch (e) { return }
    if (!Array.isArray(parsed)) return
    var clean = []
    for (var i = 0; i < parsed.length; i++) {
      var n = parsed[i]
      if (n && typeof n.id === "string" && root.idPattern.test(n.id)
          && typeof n.mtime === "number" && typeof n.firstLine === "string")
        clean.push({ id: n.id, mtime: n.mtime, firstLine: n.firstLine })
    }
    root.notes = clean
    root.notesLoaded = true
    root.listIndex = Math.max(0, Math.min(root.listIndex, clean.length - 1))
  }

  function sortNotes(list) {
    return list.slice().sort(function(a, b) { return b.mtime - a.mtime })
  }

  function displayTitle(n) {
    return n.firstLine || "Untitled"
  }

  // Stops at the first line with something on it, so a long note costs no
  // more than its opening lines on every keystroke.
  function firstLineOf(text) {
    var m = /^\s*(\S[^\n]*)/.exec(text)
    return m ? m[1].trim() : ""
  }

  function ago(ms) {
    var s = Math.max(0, (Date.now() - ms) / 1000)
    if (s < 60) return "now"
    if (s < 3600) return Math.floor(s / 60) + "m"
    if (s < 86400) return Math.floor(s / 3600) + "h"
    if (s < 7 * 86400) return Math.floor(s / 86400) + "d"
    return Qt.formatDate(new Date(ms), "MMM d")
  }

  function moveHighlight(step) {
    var last = root.sortedNotes.length - 1
    root.listIndex = Math.max(0, Math.min(last, root.listIndex + step))
    notesList.positionViewAtIndex(root.listIndex, ListView.Contain)
  }

  function openHighlighted() {
    var n = root.sortedNotes[root.listIndex]
    if (n) root.openNote(n.id)
  }

  // The edit screen only appears once the read has succeeded. Showing it
  // first would leave an empty editor whose autosave could write that
  // emptiness over a note the reader merely failed to open.
  function openNote(id) {
    if (!root.idPattern.test(id)) return
    root.listError = ""
    root.readingId = id
    notesReader.running = false
    notesReader.running = true
  }

  function newNoteId() {
    var hex = ""
    for (var i = 0; i < 4; i++) hex += "0123456789abcdef"[Math.floor(Math.random() * 16)]
    return Qt.formatDateTime(new Date(), "yyyyMMdd-HHmmss") + "-" + hex
  }

  function newNote() {
    var id = root.newNoteId()
    while (root.notes.some(function(n) { return n.id === id })) id = root.newNoteId()
    root.startEditing(id, "", true)
  }

  function startEditing(id, text, isNew) {
    saveTimer.stop()
    root.savingNow = false
    root.currentId = id
    root.currentIsNew = isNew
    root.dirtySinceOpen = false
    root.loadingNote = true
    textArea.text = text
    textArea.cursorPosition = text.length
    root.loadingNote = false
    root.view = "edit"
    root.focusView()
  }

  function writeCurrent() {
    if (root.currentId === "" || root.loadingNote) return
    if (root.currentIsNew && textArea.text.trim() === "") return
    root.savingNow = true
    notesFile.setText(textArea.text)
    root.currentIsNew = false
    root.dirtySinceOpen = true
  }

  function flushSave() {
    if (!saveTimer.running) return
    saveTimer.stop()
    root.writeCurrent()
  }

  // The write lands on its own schedule, so the listing that follows may
  // still see the old file. The row is put right from what is in the
  // editor first; the listing, and notesFile's saved signal, confirm it.
  function finishEditing() {
    root.flushSave()
    if (root.dirtySinceOpen) {
      var id = root.currentId
      var rest = root.notes.filter(function(n) { return n.id !== id })
      rest.push({ id: id, mtime: Date.now(), firstLine: root.firstLineOf(textArea.text) })
      root.notes = rest
    }
    root.showList()
  }

  function handleListKey(event) {
    if (event.key === Qt.Key_Escape) root.dismiss()
    else if (root.isSettingsShortcut(event)) root.openSettings()
    else if (event.key === Qt.Key_Up) root.moveHighlight(-1)
    else if (event.key === Qt.Key_Down) root.moveHighlight(1)
    else if (root.isEnter(event) && !(event.modifiers & Qt.ControlModifier)) root.openHighlighted()
    else if (root.isCtrl(event, Qt.Key_N)) root.newNote()
    else return
    event.accepted = true
  }
```

- [ ] **Step 6: Point reads and writes at the open note**

Replace the whole `notesFile` FileView and the `savingNow` line after it:

```qml
  FileView {
    id: notesFile
    path: root.notesPath
    watchChanges: true
    atomicWrites: true
    blockAllReads: true
    preload: false
    printErrors: false
    // Saving changes the file, which fires this. Re-reading then replaces the
    // editor's contents with what was on disk a moment ago — losing anything
    // typed while the reader was starting up, and dropping the cursor to the
    // top of the note mid-sentence. Our own writes are skipped; someone
    // else's are still picked up.
    onFileChanged: {
      if (root.savingNow) { root.savingNow = false; return }
      root.readNotes()
    }
  }
  property bool savingNow: false
```

with:

```qml
  FileView {
    id: notesFile
    path: root.currentPath
    watchChanges: true
    atomicWrites: true
    blockAllReads: true
    preload: false
    printErrors: false
    // Saving changes the file, which fires this. Re-reading then replaces the
    // editor's contents with what was on disk a moment ago, losing anything
    // typed while the reader was starting up and dropping the cursor to the
    // top of the note mid-sentence. Our own writes are skipped; someone
    // else's are still picked up, but only while that note is on screen.
    onFileChanged: {
      if (root.savingNow) { root.savingNow = false; return }
      if (root.view === "edit" && !root.currentIsNew) root.openNote(root.currentId)
    }
    onSaved: if (root.view === "list") root.refreshList()
  }
  property bool savingNow: false
```

Delete this line:

```qml
  function readNotes() { notesReader.running = false; notesReader.running = true }
```

Replace the `notesPending` property and the `notesReader` Process:

```qml
  property string notesPending: ""
  Process {
    id: notesReader
    command: ["python3", "-c", root.safeRead,
              root.notesPath, String(root.notesCeiling)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.notesPending = text
    }
    onExited: function(code) {
      if (code === 0) textArea.text = root.notesPending
      root.notesPending = ""
    }
  }
```

with:

```qml
  property string notesPending: ""
  Process {
    id: notesReader
    command: ["python3", "-c", root.safeRead,
              root.notesDir + "/" + root.readingId + ".txt", String(root.notesCeiling)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.notesPending = text
    }
    // Two callers: opening a note from the list, and re-reading the open
    // note after someone else changed it on disk.
    onExited: function(code) {
      var id = root.readingId
      var text = root.notesPending
      root.notesPending = ""
      if (code !== 0) {
        if (root.view === "list") root.listError = "Could not open that note."
        return
      }
      if (root.view === "edit" && id === root.currentId) {
        root.loadingNote = true
        textArea.text = text
        root.loadingNote = false
      } else if (root.view === "list") {
        root.startEditing(id, text, false)
      }
    }
  }
```

Replace:

```qml
    onTriggered: { root.savingNow = true; notesFile.setText(textArea.text) }
```

with:

```qml
    onTriggered: root.writeCurrent()
```

- [ ] **Step 7: Run migrate and list from the helper**

Replace:

```qml
  Process {
    id: ensureDirsProc
    command: ["mkdir", "-p", root.stateDir]
  }
```

with:

```qml
  Process {
    id: ensureDirsProc
    command: ["mkdir", "-p", root.stateDir]
  }

  Process {
    id: migrateProc
    command: ["python3", "-I", root.helperPath, "migrate", root.stateDir]
    onExited: function(code) { root.refreshList() }
  }

  Process {
    id: listProc
    command: ["python3", "-I", root.helperPath, "list", root.stateDir]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.listPending = text
    }
    onExited: function(code) {
      if (code === 0) root.loadList(root.listPending)
      root.listPending = ""
    }
  }
```

In `Component.onCompleted`, replace:

```qml
      root.readNotes()
```

with:

```qml
      migrateProc.running = true
```

- [ ] **Step 8: Add the list, the hint, and the header title to the card**

Replace:

```qml
        ScrollView {
          id: notesScroll
          visible: !root.settingsOpen
```

with:

```qml
        ListView {
          id: notesList
          visible: !root.settingsOpen && root.view === "list"
          anchors.fill: parent
          anchors.topMargin: headerRow.height + Style.spacing.xs
          clip: true
          model: root.sortedNotes
          currentIndex: root.listIndex
          keyNavigationEnabled: false
          boundsBehavior: Flickable.StopAtBounds

          delegate: Item {
            width: notesList.width
            height: Math.round(root.fontSize * 2.2)

            Rectangle {
              anchors.fill: parent
              radius: root.cornerRadius
              visible: index === root.listIndex
              color: Style.selectionFillFor(root.foreground, Color.accent)
            }

            Text {
              id: rowAgo
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.sm
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.ago(modelData.mtime)
              color: Qt.darker(root.foreground, 1.4)
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.sm
              anchors.right: rowAgo.left
              anchors.rightMargin: Style.spacing.sm
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              elide: Text.ElideRight
              text: root.displayTitle(modelData)
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: root.fontSize
            }

            MouseArea {
              anchors.fill: parent
              onClicked: { root.listIndex = index; root.openNote(modelData.id) }
            }
          }

          Keys.onPressed: function(event) { root.handleListKey(event) }
        }

        Text {
          visible: !root.settingsOpen && root.view === "list"
                   && (root.listError !== "" || (root.notesLoaded && root.sortedNotes.length === 0))
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          horizontalAlignment: Text.AlignHCenter
          text: root.listError !== "" ? root.listError : "No notes yet. Ctrl+N to start one."
          color: root.listError !== "" ? Color.urgent : Qt.darker(root.foreground, 1.6)
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        ScrollView {
          id: notesScroll
          visible: !root.settingsOpen && root.view === "edit"
```

Replace the TextArea's placeholder, key handler and text handler:

```qml
            placeholderText: "Scratchpad…"
```

with:

```qml
            placeholderText: "Write here. Ctrl+Enter when done."
```

and:

```qml
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) {
                root.dismiss()
                event.accepted = true
              } else if (root.isSettingsShortcut(event)) {
                root.openSettings()
                event.accepted = true
              }
            }

            onTextChanged: saveTimer.restart()
```

with:

```qml
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) root.dismiss()
              else if (root.isSettingsShortcut(event)) root.openSettings()
              else if (root.isEnter(event) && (event.modifiers & Qt.ControlModifier)) root.finishEditing()
              else return
              event.accepted = true
            }

            onTextChanged: if (!root.loadingNote) saveTimer.restart()
```

Insert the header title just before the header row. Replace:

```qml
        Row {
          id: headerRow
```

with:

```qml
        Text {
          id: headerTitle
          visible: !root.settingsOpen
          anchors.left: parent.left
          anchors.right: headerRow.left
          anchors.rightMargin: Style.spacing.sm
          anchors.verticalCenter: headerRow.verticalCenter
          textFormat: Text.PlainText
          elide: Text.ElideRight
          text: root.view === "list" ? "Notes" : (root.firstLineOf(textArea.text) || "Untitled")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }

        Row {
          id: headerRow
```

Check nothing still mentions the old names: `grep -n -E 'notesPath|readNotes' Panel.qml` must print nothing.

- [ ] **Step 9: Live check**

Tell the user you are about to drive the desktop. Run the live check recipe and confirm each item, with a screenshot where it says so:

1. Journal shows no QML errors after restart.
2. `ls ~/.local/state/omarchy/omascratch` shows `notes/` and `notes.txt.bak`; `notes/` holds one file whose content equals `notes.txt.bak` (migration of the real note).
3. Open the panel: the list shows that one note, highlighted, header `Notes`, right column `now`/`Xm` (screenshot).
4. Enter: edit screen with the note's text, header shows its first line (screenshot).
5. `wtype ' edited'`, then Ctrl+Enter: back on the list, the row's title/time reflect the edit; `cat` the file to confirm it was written.
6. Ctrl+N, type `second note`, Ctrl+Enter: two rows, `second note` on top.
7. Ctrl+N then Ctrl+Enter with nothing typed: still two rows, and `ls notes/` still shows two files.
8. Down, Down (stops at the end), Up, Enter opens the highlighted note.
9. Review Focus 4: on the edit screen run `wtype quick; omarchy-shell shell toggle io.github.weedwhitesandwine.omascratch` in one line, so the panel closes well inside the 400 ms timer (toggle goes through `dismiss()`, the same path as a click elsewhere clearing the focus grab). `cat` the note file: it ends with `quick`. Then ask the user to repeat it once by typing and clicking another window.
10. Esc on the list closes the panel; reopening lands on the list with the first row highlighted.
11. Ctrl+, opens settings from both screens, and Esc returns to the screen it came from.

If any item fails, fix it before committing.

- [ ] **Step 10: Commit**

```bash
cd ~/Code/omascratch
git add Panel.qml
git commit -m "Open on a list of notes, each saved to its own file

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Sort cycling with Ctrl+S

**Files:**
- Modify: `Panel.qml`

**Interfaces:**
- Consumes: `notes`, `listIndex`, `sortedNotes`, `sortNotes(list)`, `displayTitle(n)`, `handleListKey(event)`, `headerTitle` from Task 2; existing `loadSettings`, `flushSettings`, `scheduleSettingsSave`.
- Produces: `sortMode` ("latest" | "oldest" | "az" | "za"), `sortModes` (array), `sortLabels` (object), `cycleSort()`, `sortNotes(list, mode) -> array` (signature changes; Task 4 extends it again).

- [ ] **Step 1: Add the sort state**

Replace:

```qml
  readonly property var sortedNotes: root.sortNotes(root.notes)
```

with:

```qml
  property string sortMode: "latest"
  readonly property var sortModes: ["latest", "oldest", "az", "za"]
  readonly property var sortLabels: ({ latest: "Latest first", oldest: "Oldest first", az: "A to Z", za: "Z to A" })
  readonly property var sortedNotes: root.sortNotes(root.notes, root.sortMode)
```

- [ ] **Step 2: Sort by mode, and cycle**

Replace:

```qml
  function sortNotes(list) {
    return list.slice().sort(function(a, b) { return b.mtime - a.mtime })
  }
```

with:

```qml
  // Titles compare case-insensitively and by locale, so accented letters sit
  // with their plain forms instead of after the end of the alphabet. Equal
  // titles fall back to the newest first.
  function sortNotes(list, mode) {
    return list.slice().sort(function(a, b) {
      if (mode === "oldest") return a.mtime - b.mtime
      if (mode === "az" || mode === "za") {
        var c = root.displayTitle(a).toLowerCase().localeCompare(root.displayTitle(b).toLowerCase())
        if (c !== 0) return mode === "az" ? c : -c
      }
      return b.mtime - a.mtime
    })
  }

  function cycleSort() {
    var i = root.sortModes.indexOf(root.sortMode)
    root.sortMode = root.sortModes[(i + 1) % root.sortModes.length]
    root.listIndex = 0
    notesList.positionViewAtIndex(0, ListView.Beginning)
  }
```

Replace:

```qml
    else if (root.isCtrl(event, Qt.Key_N)) root.newNote()
```

with:

```qml
    else if (root.isCtrl(event, Qt.Key_N)) root.newNote()
    else if (root.isCtrl(event, Qt.Key_S)) root.cycleSort()
```

- [ ] **Step 3: Remember the sort, and show it**

In `loadSettings`, replace:

```qml
    if (typeof parsed.cardHeight === "number") root.setCardHeight(parsed.cardHeight)
```

with:

```qml
    if (typeof parsed.cardHeight === "number") root.setCardHeight(parsed.cardHeight)
    if (root.sortModes.indexOf(parsed.sort) !== -1) root.sortMode = parsed.sort
```

In `flushSettings`, replace:

```qml
      cardHeight: root.cardHeight
    }, null, 2) + "\n")
```

with:

```qml
      cardHeight: root.cardHeight,
      sort: root.sortMode
    }, null, 2) + "\n")
```

Replace:

```qml
  onCardHeightChanged: scheduleSettingsSave()
```

with:

```qml
  onCardHeightChanged: scheduleSettingsSave()
  onSortModeChanged: scheduleSettingsSave()
```

In `headerTitle`, replace:

```qml
          text: root.view === "list" ? "Notes" : (root.firstLineOf(textArea.text) || "Untitled")
```

with:

```qml
          text: root.view === "list" ? "Notes · " + root.sortLabels[root.sortMode]
                                     : (root.firstLineOf(textArea.text) || "Untitled")
```

- [ ] **Step 4: Live check**

Create a known set first: with the panel open, use Ctrl+N to add notes titled `banana`, `Apple`, `άλφα`, `ωμέγα`, `αλφάβητο` (Ctrl+Enter after each). Then:

1. Header reads `Notes · Latest first`; newest note on top.
2. Ctrl+S: `Oldest first`, order reversed. Ctrl+S: `A to Z`: `Apple`, `banana` before the Greek; `άλφα` and `αλφάβητο` together near the top of the Greek, `ωμέγα` last (Review Focus 5). Ctrl+S: `Z to A`, exact reverse. Ctrl+S: back to `Latest first`. Screenshot each.
3. Highlight returns to the first row on every Ctrl+S.
4. Set `A to Z`, run `omarchy-restart-shell`, reopen: still `A to Z`; `cat settings.json` shows `"sort": "az"`. Set it back to `Latest first`.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/omascratch
git add Panel.qml
git commit -m "Cycle the note order with Ctrl+S and remember it

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Custom titles with Ctrl+T

**Files:**
- Modify: `Panel.qml`

**Interfaces:**
- Consumes: `currentId`, `currentIsNew`, `notes`, `notesLoaded`, `idPattern`, `savingNow`, `dirtySinceOpen`, `notesFile`, `showList()`, `focusView()`, `firstLineOf(text)`, `sortNotes(list, mode)`, `headerTitle`, `migrateProc`, `listProc` from Tasks 2 and 3; existing `safeRead`, `settingsCeiling`.
- Produces: `titles` (object id -> string), `titlesLoaded` (bool), `editingTitle` (bool), `titlesPath`, `readTitles()`, `loadTitles(json)`, `setTitle(id, title) -> bool`, `beginTitleEdit()`, `confirmTitle()`, `cancelTitle()`, `displayTitle(n, titles) -> string`, `sortNotes(list, mode, titles) -> array`, item `titleField`. Task 5 calls `setTitle(id, "")` after a delete.

- [ ] **Step 1: Add the title state**

Replace:

```qml
  readonly property var sortedNotes: root.sortNotes(root.notes, root.sortMode)
```

with:

```qml
  readonly property string titlesPath: stateDir + "/titles.json"
  // Only notes given a title with Ctrl+T appear here. titlesLoaded stays
  // false after a read that failed, and nothing writes the file until it is
  // true: writing then would replace every title with the one being set.
  property var titles: ({})
  property bool titlesLoaded: false
  property string titlesPending: ""
  property bool editingTitle: false
  readonly property var sortedNotes: root.sortNotes(root.notes, root.sortMode, root.titles)
```

- [ ] **Step 2: Read and write titles.json**

Replace:

```qml
    onExited: function(code) { root.refreshList() }
```

with:

```qml
    onExited: function(code) { root.refreshList(); root.readTitles() }
```

Replace:

```qml
    onExited: function(code) {
      if (code === 0) root.loadList(root.listPending)
      root.listPending = ""
    }
  }
```

with:

```qml
    onExited: function(code) {
      if (code === 0) root.loadList(root.listPending)
      root.listPending = ""
    }
  }

  Process {
    id: titlesReader
    command: ["python3", "-c", root.safeRead,
              root.titlesPath, String(root.settingsCeiling)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.titlesPending = text
    }
    // Exit 2 is the reader's "not there", which is a first run and an empty
    // set of titles. Any other failure leaves titles unloaded.
    onExited: function(code) {
      if (code === 0) root.loadTitles(root.titlesPending)
      else if (code === 2) { root.titles = {}; root.titlesLoaded = true }
      root.titlesPending = ""
    }
  }

  FileView {
    id: titlesFile
    path: root.titlesPath
    watchChanges: false
    atomicWrites: true
    blockAllReads: true
    preload: false
    printErrors: false
  }
```

- [ ] **Step 3: Title functions**

Replace:

```qml
  function displayTitle(n) {
    return n.firstLine || "Untitled"
  }
```

with:

```qml
  function displayTitle(n, titles) {
    return (titles && titles[n.id]) || n.firstLine || "Untitled"
  }

  function readTitles() { titlesReader.running = false; titlesReader.running = true }

  // A hand-edited file can hold anything, so only well-formed ids with short
  // string titles are kept.
  function loadTitles(json) {
    var parsed
    try { parsed = JSON.parse(json || "{}") } catch (e) { return }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return
    var clean = {}
    for (var k in parsed)
      if (root.idPattern.test(k) && typeof parsed[k] === "string" && parsed[k].trim() !== "")
        clean[k] = parsed[k].trim().slice(0, 200)
    root.titles = clean
    root.titlesLoaded = true
  }

  // Titles of notes that no longer exist are dropped here, but only against a
  // list that has actually been read, or an unread list would drop them all.
  function setTitle(id, title) {
    if (!root.titlesLoaded || !root.idPattern.test(id)) return false
    var keep = {}
    for (var i = 0; i < root.notes.length; i++) keep[root.notes[i].id] = true
    if (root.currentId !== "") keep[root.currentId] = true
    var next = {}
    for (var k in root.titles)
      if (k !== id && (!root.notesLoaded || keep[k])) next[k] = root.titles[k]
    var t = title.trim().slice(0, 200)
    if (t !== "") next[id] = t
    root.titles = next
    titlesFile.setText(JSON.stringify(next, null, 2) + "\n")
    return true
  }

  function beginTitleEdit() {
    if (!root.titlesLoaded) return
    root.editingTitle = true
    titleField.text = root.titles[root.currentId] || ""
    Qt.callLater(function() { titleField.forceActiveFocus(); titleField.selectAll() })
  }

  // A titled note is not a blank one, so a new note gets its file as soon as
  // it has a title, even with nothing written in it yet.
  function confirmTitle() {
    var t = titleField.text.trim()
    if (root.setTitle(root.currentId, t) && t !== "" && root.currentIsNew) {
      root.savingNow = true
      notesFile.setText(textArea.text)
      root.currentIsNew = false
      root.dirtySinceOpen = true
    }
    root.editingTitle = false
    textArea.forceActiveFocus()
  }

  function cancelTitle() {
    root.editingTitle = false
    textArea.forceActiveFocus()
  }
```

Replace the Task 3 `sortNotes` so it uses titles:

```qml
  function sortNotes(list, mode) {
    return list.slice().sort(function(a, b) {
      if (mode === "oldest") return a.mtime - b.mtime
      if (mode === "az" || mode === "za") {
        var c = root.displayTitle(a).toLowerCase().localeCompare(root.displayTitle(b).toLowerCase())
```

with:

```qml
  function sortNotes(list, mode, titles) {
    return list.slice().sort(function(a, b) {
      if (mode === "oldest") return a.mtime - b.mtime
      if (mode === "az" || mode === "za") {
        var c = root.displayTitle(a, titles).toLowerCase().localeCompare(root.displayTitle(b, titles).toLowerCase())
```

In `showList`, replace:

```qml
    root.view = "list"
    root.listIndex = 0
```

with:

```qml
    root.view = "list"
    root.editingTitle = false
    root.listIndex = 0
```

In `finishEditing`, a title edit still open is dropped by `showList`; no change needed there.

- [ ] **Step 4: Wire the key, the field and the displays**

In the TextArea key handler, replace:

```qml
              else if (root.isEnter(event) && (event.modifiers & Qt.ControlModifier)) root.finishEditing()
```

with:

```qml
              else if (root.isEnter(event) && (event.modifiers & Qt.ControlModifier)) root.finishEditing()
              else if (root.isCtrl(event, Qt.Key_T)) root.beginTitleEdit()
```

In the list delegate, replace:

```qml
              text: root.displayTitle(modelData)
```

with:

```qml
              text: root.displayTitle(modelData, root.titles)
```

In `headerTitle`, replace:

```qml
          visible: !root.settingsOpen
          anchors.left: parent.left
          anchors.right: headerRow.left
```

with:

```qml
          visible: !root.settingsOpen && !root.editingTitle
          anchors.left: parent.left
          anchors.right: headerRow.left
```

and replace:

```qml
                                     : (root.firstLineOf(textArea.text) || "Untitled")
```

with:

```qml
                                     : (root.titles[root.currentId] || root.firstLineOf(textArea.text) || "Untitled")
```

Then insert the field directly after the `headerTitle` Text block (before `Row { id: headerRow`). `TextField` here resolves to the shell kit's `qs.Ui` TextField (it is imported after `QtQuick.Controls`), which takes `foreground` and `verticalPadding`:

```qml
        TextField {
          id: titleField
          visible: !root.settingsOpen && root.editingTitle
          anchors.left: parent.left
          anchors.right: headerRow.left
          anchors.rightMargin: Style.spacing.sm
          anchors.verticalCenter: headerRow.verticalCenter
          foreground: root.foreground
          verticalPadding: Style.spacing.xs
          font.family: root.fontFamily
          placeholderText: "Title (empty uses the first line)"
          Keys.onPressed: function(event) {
            if (root.isEnter(event)) root.confirmTitle()
            else if (event.key === Qt.Key_Escape) root.cancelTitle()
            else return
            event.accepted = true
          }
        }
```

- [ ] **Step 5: Live check**

1. Open a note, Ctrl+T: header becomes an input, empty, placeholder shown (screenshot). Type `Groceries`, Enter: header shows `Groceries`, focus back in the text (typing goes into the note). `cat titles.json` shows the id with `Groceries`.
2. Ctrl+Enter: the list row reads `Groceries`, not the first line. In `A to Z` it sorts as `Groceries`.
3. Ctrl+T on it, Esc: title unchanged. Ctrl+T, clear the field (`wtype -M ctrl a -m ctrl`, `wtype -k BackSpace`), Enter: header and row fall back to the first line; the id is gone from `titles.json`.
4. Review Focus 3: Ctrl+N, Ctrl+T, `Empty but titled`, Enter, Ctrl+Enter: the row `Empty but titled` exists and `ls notes/` has its (empty) file.
5. Review Focus 2: `cp titles.json "$QA/titles.ok"; chmod 000 titles.json; omarchy-restart-shell`, open a note, Ctrl+T: nothing happens (no input appears). `chmod 600 titles.json`, `cmp titles.json "$QA/titles.ok"`: identical. Restart again and confirm Ctrl+T works.
6. Esc while the title input is open: input closes, focus returns to the note, panel stays open.

- [ ] **Step 6: Commit**

```bash
cd ~/Code/omascratch
git add Panel.qml
git commit -m "Title a note with Ctrl+T

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Delete with Ctrl+D, confirmed by a second press

**Files:**
- Modify: `Panel.qml`

**Interfaces:**
- Consumes: helper CLI `delete` from Task 1; `sortedNotes`, `listIndex`, `listError`, `refreshList()`, `setTitle(id, title)`, `titlesLoaded`, `handleListKey` (Task 3 version), `showList()` (Task 4 version), `isBareModifier(key)` (existing).
- Produces: `armedDeleteId` (string), `deletingId` (string), `deleteNote(id)`, item `deleteProc`.

- [ ] **Step 1: Delete state and process**

Replace:

```qml
  property bool editingTitle: false
```

with:

```qml
  property bool editingTitle: false
  // The row waiting for its second Ctrl+D. Anything else clears it.
  property string armedDeleteId: ""
  property string deletingId: ""
```

Replace the `titlesFile` FileView block (added in Task 4):

```qml
  FileView {
    id: titlesFile
    path: root.titlesPath
    watchChanges: false
    atomicWrites: true
    blockAllReads: true
    preload: false
    printErrors: false
  }
```

with the same block followed by the delete process:

```qml
  FileView {
    id: titlesFile
    path: root.titlesPath
    watchChanges: false
    atomicWrites: true
    blockAllReads: true
    preload: false
    printErrors: false
  }

  Process {
    id: deleteProc
    onExited: function(code) {
      if (code === 0 && root.titlesLoaded && root.titles[root.deletingId]) root.setTitle(root.deletingId, "")
      else if (code !== 0) root.listError = "Could not delete that note."
      root.deletingId = ""
      root.refreshList()
    }
  }
```

- [ ] **Step 2: Arm, confirm, disarm**

Replace the whole `handleListKey` function (Task 3 version):

```qml
  function handleListKey(event) {
    if (event.key === Qt.Key_Escape) root.dismiss()
    else if (root.isSettingsShortcut(event)) root.openSettings()
    else if (event.key === Qt.Key_Up) root.moveHighlight(-1)
    else if (event.key === Qt.Key_Down) root.moveHighlight(1)
    else if (root.isEnter(event) && !(event.modifiers & Qt.ControlModifier)) root.openHighlighted()
    else if (root.isCtrl(event, Qt.Key_N)) root.newNote()
    else if (root.isCtrl(event, Qt.Key_S)) root.cycleSort()
    else return
    event.accepted = true
  }
```

with:

```qml
  // A bare Ctrl press arrives as a key of its own between the two Ctrl+D
  // presses, so modifiers alone leave the armed row armed.
  function handleListKey(event) {
    if (root.isBareModifier(event.key)) return
    var highlighted = root.sortedNotes[root.listIndex]
    if (root.isCtrl(event, Qt.Key_D)) {
      if (highlighted && root.armedDeleteId === highlighted.id) root.deleteNote(highlighted.id)
      else root.armedDeleteId = highlighted ? highlighted.id : ""
      event.accepted = true
      return
    }
    root.armedDeleteId = ""
    if (event.key === Qt.Key_Escape) root.dismiss()
    else if (root.isSettingsShortcut(event)) root.openSettings()
    else if (event.key === Qt.Key_Up) root.moveHighlight(-1)
    else if (event.key === Qt.Key_Down) root.moveHighlight(1)
    else if (root.isEnter(event) && !(event.modifiers & Qt.ControlModifier)) root.openHighlighted()
    else if (root.isCtrl(event, Qt.Key_N)) root.newNote()
    else if (root.isCtrl(event, Qt.Key_S)) root.cycleSort()
    else return
    event.accepted = true
  }

  function deleteNote(id) {
    root.armedDeleteId = ""
    if (!root.idPattern.test(id) || deleteProc.running) return
    root.deletingId = id
    deleteProc.command = ["python3", "-I", root.helperPath, "delete", root.stateDir, id]
    deleteProc.running = true
  }
```

In `showList`, replace:

```qml
    root.editingTitle = false
    root.listIndex = 0
```

with:

```qml
    root.editingTitle = false
    root.armedDeleteId = ""
    root.listIndex = 0
```

- [ ] **Step 3: Show the armed row**

In the delegate's `rowAgo` Text, replace:

```qml
              text: root.ago(modelData.mtime)
              color: Qt.darker(root.foreground, 1.4)
```

with:

```qml
              text: modelData.id === root.armedDeleteId ? "Ctrl+D again to delete" : root.ago(modelData.mtime)
              color: modelData.id === root.armedDeleteId ? Color.urgent : Qt.darker(root.foreground, 1.4)
```

In the delegate's MouseArea, replace:

```qml
              onClicked: { root.listIndex = index; root.openNote(modelData.id) }
```

with:

```qml
              onClicked: { root.armedDeleteId = ""; root.listIndex = index; root.openNote(modelData.id) }
```

- [ ] **Step 4: Live check**

1. Highlight a throwaway note, Ctrl+D: its row's right side reads `Ctrl+D again to delete` in the urgent colour (screenshot). Down: the prompt disappears.
2. Back on it, Ctrl+D then Ctrl+D: the row is gone, the highlight sits on a neighbouring row, `ls trash/` shows the file.
3. Review Focus 1: Ctrl+D, then press and release Ctrl alone (`wtype -P Control_L -p Control_L`), then Ctrl+D: the note is deleted (the bare Ctrl did not disarm).
4. Delete the `Groceries` note from Task 4: its id disappears from `titles.json`.
5. Ctrl+D on an empty list does nothing and shows no error.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/omascratch
git add Panel.qml
git commit -m "Delete a note with Ctrl+D twice, into the trash folder

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs, version, and the full pass

**Files:**
- Modify: `README.md`, `manifest.json`

**Interfaces:**
- Consumes: everything above.
- Produces: the finished branch, pushed.

- [ ] **Step 1: Manifest**

In `manifest.json`, replace `"version": "0.2.0",` with `"version": "0.3.0",` and replace the description's opening `"A quick-note scratchpad that docks to a screen corner.` with `"Quick standing notes that dock to a screen corner: a keyboard-driven list of notes, each saved to its own file.`

Validate: `omarchy plugin validate ~/Code/omascratch` must pass.

- [ ] **Step 2: README**

In `README.md`, replace the first Features bullet `- Notes autosave to disk as you type (debounced, no save button).` with:

```markdown
- Several standing notes, each in its own file, picked from a list that the
  panel opens on. Notes autosave as you type (no save button).
```

Then add this section directly before `## Install`:

```markdown
## Multiple notes

The panel opens on a list of your notes with the first one highlighted.

| On the list | |
|---|---|
| Up / Down | Move the highlight |
| Enter | Open the highlighted note |
| Ctrl+N | New note |
| Ctrl+S | Sort: latest first, oldest first, A to Z, Z to A |
| Ctrl+D, Ctrl+D | Delete the highlighted note (it goes to the trash folder) |
| Esc | Close the panel |

| In a note | |
|---|---|
| Ctrl+Enter | Save and go back to the list |
| Ctrl+T | Give the note a title (empty goes back to using its first line) |
| Esc | Save and close the panel |

A note's title is its first line unless you set one with Ctrl+T. Ctrl+,
opens settings from either screen.

Notes live in `~/.local/state/omarchy/omascratch/notes/`, one plain text
file each. Custom titles are kept in `titles.json` next to it, and deleted
notes are moved to `trash/` rather than erased. Upgrading from a version
with a single scratchpad turns it into your first note and keeps the
original as `notes.txt.bak`.
```

Check: `grep -c '—' README.md` counts only dashes that were already in the upstream README (compare with `git show upstream/main:README.md | grep -c '—'`); none of the new text adds any.

- [ ] **Step 3: Full pass**

Run `python3 -I -m unittest discover -s tests -v` (all pass), then restart the shell and walk every key in both tables of the spec once more, plus: the panel in all four corners (settings) still docks correctly, font size changes apply to the list and editor, Pin still keeps the panel open on click-away. Screenshot the list and the edit screen for the user.

- [ ] **Step 4: Commit and push the branch**

```bash
cd ~/Code/omascratch
git add README.md manifest.json
git commit -m "Document multiple notes, version 0.3.0

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push origin multi-notes
```

Then tell the user: the live plugin is still the symlink to `~/Code/omascratch` (so it keeps working on this branch); the original install is in `~/.local/share/omascratch-upstream-backup`, the pre-QA state in `~/.local/share/omascratch-state-backup-20261013`; merging `multi-notes` into the fork's `main` and switching to `omarchy plugin add https://github.com/alikanet/omascratch.git --enable` is their call.
