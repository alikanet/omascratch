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

    def test_keeps_last_edited_time(self):
        self.write("notes.txt", "dated", mtime=1700000000)
        helper.migrate(self.state)
        moved = os.path.join(self.notes, self.notes_files()[0])
        self.assertEqual(int(os.stat(moved).st_mtime), 1700000000)

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
