# Multiple notes: design

Date: 2026-10-13
Status: approved for planning

## Goal

Turn Omascratch from one scratchpad into a handful of standing notes the user
flips between. Expected size is a few notes (roughly 2 to 20), not hundreds.
Everything is keyboard driven; mouse support is a bonus, not a requirement.

## Screens

The panel has two main screens plus the existing settings view.

### List screen (the main screen)

- Opening the panel always lands here, with the first row highlighted.
- Header: `Notes · <sort label>` on the left, Pin and gear buttons on the
  right as today.
- One row per note: title on the left, relative edit time on the right
  (`now`, `5m`, `2h`, `3d`, then a date like `Oct 2`).
- An empty list shows a hint: `No notes yet. Ctrl+N to start one.`

| Key | Action |
|---|---|
| Up / Down | Move the highlight (stops at the ends, no wrap) |
| Enter | Open the highlighted note on the edit screen |
| Ctrl+N | Create a new note and open it on the edit screen |
| Ctrl+S | Cycle sort: Latest first, Oldest first, A to Z, Z to A |
| Ctrl+D | Arm delete on the highlighted row (row shows `Ctrl+D again to delete`); a second Ctrl+D deletes it; any other key or moving the highlight disarms |
| Ctrl+, | Open settings (unchanged) |
| Esc | Close the panel |

Clicking a row opens it.

### Edit screen

- The existing text area, filling the card as today.
- Header shows the note's title on the left.

| Key | Action |
|---|---|
| Ctrl+Enter | Save now and return to the list |
| Ctrl+T | Turn the header title into an input field |
| Ctrl+, | Open settings (returning from settings lands back on this note) |
| Esc | Save now and close the panel (next open lands on the list) |

Title input (after Ctrl+T): Enter confirms, Esc cancels and returns focus to
the text, and confirming an empty value clears the custom title so the note
falls back to its first line.

## Titles and sorting

- Displayed title is the custom title if one is set, otherwise the first
  non-blank line of the note, trimmed. A note with no text shows `Untitled`.
- Long titles are elided at the row's width.
- Sort modes:
  - Latest first: by last edited time, newest at the top (default).
  - Oldest first: by last edited time, oldest at the top.
  - A to Z / Z to A: by displayed title, case-insensitive, ties broken by
    last edited time.
- The chosen sort is remembered across restarts.

## Storage

All under `~/.local/state/omarchy/omascratch/`:

```
notes/<id>.txt      one file per note, plain text, nothing else in it
titles.json         {"<id>": "Custom title", ...}  only notes with a Ctrl+T title
trash/<id>.txt      deleted notes
settings.json       existing file, gains "sort": "latest|oldest|az|za"
notes.txt.bak       the old single note, after migration
```

- **Note id**: creation time plus a random suffix, `YYYYMMDD-HHMMSS-xxxx`
  (`xxxx` is 4 lowercase hex chars). Every id read from disk or from
  `titles.json` is checked against `^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$`;
  anything else is ignored, so a stray file can never become a path to
  write to.
- **Which notes exist** is decided by the `notes/` directory, not by an
  index. A file added by hand appears in the list; a title in `titles.json`
  for a note that no longer exists is ignored and dropped on the next title
  save.
- **Last edited** is the file's modification time.
- **Writes** use the same atomic `FileView.setText` approach as today, with
  the path pointed at the open note.
- **New notes** have no file until their first non-empty save. A new note
  left blank therefore leaves nothing behind. An existing note emptied by
  the user is kept as an empty file (delete it with Ctrl+D).
- **Delete** moves `notes/<id>.txt` to `trash/<id>.txt` and drops its title.
  Nothing in the panel empties the trash.

## The list helper

A small Python script shipped with the plugin (`omascratch-notes.py`), run
through `Process` like the existing reader. Subcommands:

- `list <stateDir>`: prints JSON `[{"id", "mtime", "firstLine"}, ...]` for
  every valid-id regular file in `notes/`. It opens each file with the same
  rules as the existing `safeRead` (no symlinks, regular files only) and
  reads at most the first 4 KiB to find the first line.
- `delete <stateDir> <id>`: validates the id, creates `trash/` if needed and
  renames the file into it.
- `migrate <stateDir>`: if `notes/` does not exist, creates it; then, if
  `notes.txt` exists and has non-blank text, writes it as the first note
  and renames `notes.txt` to `notes.txt.bak`. Running it again does nothing.

Opening a single note for editing keeps using the existing `safeRead`
reader with its 4 MiB ceiling.

The list refreshes when the panel opens, when returning to the list, and
after a delete. There is no directory watcher; hand-added files show up on
the next refresh.

## Saving behaviour

- Typing restarts the existing 400 ms debounce timer; when it fires, the
  open note is written.
- Leaving the edit screen by any route (Ctrl+Enter, Esc, closing the panel
  by clicking away) flushes a pending save first.
- The existing "skip the change notification caused by our own write" logic
  stays, scoped to the open note.
- A read that fails (non-zero exit from the reader) never fills the editor,
  so autosave can never write a blank over a real note. Same rule as today.

## Migration

On startup the panel runs `migrate` before the first list. Existing users
therefore see their current scratchpad as the only note, untouched, and the
original is kept as `notes.txt.bak`.

## Out of scope

- Search, folders, tags, pinning individual notes.
- Restoring from trash inside the panel (it is a plain folder).
- Multiple panels or notes open at once.
- Syncing or exporting.

## Testing

- `omascratch-notes.py` gets a `unittest` test file
  (`tests/test_notes_helper.py`) covering: listing valid and invalid file
  names, symlinks refused, first-line extraction (blank leading lines,
  missing trailing newline, empty file), delete validation and move,
  migrate (fresh install, existing notes.txt, blank notes.txt, already
  migrated).
- The QML has no test harness, so the panel is checked against a manual QA
  checklist in the live Omarchy shell: every key in both tables above, all
  four sort modes, Ctrl+T set and clear, blank new note discarded, delete
  arm and disarm, migration of a real `notes.txt`, and settings round trip
  from both screens.

## Install during development

The live plugin folder
`~/.config/omarchy/plugins/io.github.weedwhitesandwine.omascratch` is
replaced by a symlink to `~/Code/omascratch`, so changes are picked up by
reloading the shell. Once the branch is merged on the fork, a normal
`omarchy plugin add https://github.com/alikanet/omascratch.git --enable`
replaces the symlink.

## Docs

README gains a "Multiple notes" section with both key tables; manifest
description mentions multiple notes; version goes to 0.3.0.
