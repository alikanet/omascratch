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
