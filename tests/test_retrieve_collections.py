from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("bash"), "Bash is required")
class RetrieveCollectionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "GEMS checkout"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        self.script = scripts / "retrieve_collections.sh"
        shutil.copyfile(Path(__file__).parents[1] / "scripts" / self.script.name, self.script)
        python = self.repo / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\0" "$@" >> "$CALL_LOG"\n'
            'printf "\\0" >> "$CALL_LOG"\n'
            'printf "Button 2 follow-up command\\n"\n'
            'for arg in "$@"; do\n'
            '  if [[ "$arg" == "--collection-title=Fail" ]]; then exit 7; fi\n'
            'done\n'
            'if [[ "${OMIT_COMMAND:-}" != 1 ]]; then\n'
            '  printf "%s\\n" "/fake/python -m gems --headless --source \'manifest file.json\' --output \'run folder\'"\n'
            'fi\n',
        )
        python.chmod(0o755)
        self.output = self.root / "output's folder"
        self.output.mkdir()
        self.titles = self.root / "titles.txt"
        self.log = self.root / "calls"
        self.environment = {**os.environ, "CALL_LOG": str(self.log)}
        self.environment.pop("GEMS_ENV_FILE", None)

    def run_script(self, *args):
        return subprocess.run(
            ["bash", str(self.script), *map(str, args)], cwd=self.root,
            env=self.environment, text=True, capture_output=True, timeout=15,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [part.decode().split("\0") for part in self.log.read_bytes().split(b"\0\0") if part]

    def saved_commands(self):
        files = list(self.output.glob("button-2-commands-*"))
        self.assertEqual(1, len(files))
        return files[0], files[0].read_text()

    def test_titles_are_literal_trimmed_and_support_crlf_and_no_final_newline(self):
        titles = ["Social Justice at Grinnell", "Women's history", 'Title "quoted" #1',
                  r"Back\slash; $(touch SHOULD_NOT_EXIST)", "--title"]
        self.titles.write_bytes(("\r\n  " + titles[0] + "  \r\n\r\n" + "\r\n".join(titles[1:])).encode())
        result = self.run_script(self.titles, self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls()
        self.assertEqual(len(titles), len(calls))
        for title, call in zip(titles, calls):
            self.assertEqual(
                ["-m", "gems", "--headless", "--retrieve", f"--collection-title={title}",
                 "--output", str(self.output.resolve())], call,
            )
        self.assertFalse((self.repo / "SHOULD_NOT_EXIST").exists())
        self.assertEqual(len(titles), result.stdout.count("Button 2 follow-up command"))
        self.assertIn("Completed button 1 for 5 collection(s)", result.stdout)
        path, saved = self.saved_commands()
        self.assertEqual(5, saved.count("/fake/python -m gems --headless"))
        for title in titles:
            self.assertIn(f"# Collection: {title}\n", saved)
        self.assertIn(str(path), result.stdout)
        self.assertEqual(0, path.stat().st_mode & 0o077)
        syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        self.assertEqual(0, syntax.returncode, syntax.stderr)

    def test_failure_stops_immediately_and_preserves_exit_status(self):
        self.titles.write_text("First\nFail\nNever run\n")
        result = self.run_script(self.titles, self.output)
        self.assertEqual(7, result.returncode)
        self.assertEqual(2, len(self.calls()))
        self.assertIn("Stopped at line 2: Fail", result.stderr)
        self.assertIn("Completed 1 collection(s)", result.stderr)
        self.assertNotIn("Never run", result.stdout)
        path, saved = self.saved_commands()
        self.assertIn("# Collection: First\n", saved)
        self.assertNotIn("# Collection: Fail", saved)
        self.assertEqual(1, saved.count("/fake/python -m gems --headless"))
        self.assertIn(str(path), result.stderr)

    def test_repeated_batches_keep_separate_command_files(self):
        self.titles.write_text("First\n")
        for _ in range(2):
            result = self.run_script(self.titles, self.output)
            self.assertEqual(0, result.returncode, result.stderr)
        files = list(self.output.glob("button-2-commands-*"))
        self.assertEqual(2, len(files))
        self.assertTrue(all(path.read_text().count("/fake/python -m gems --headless") == 1 for path in files))

    def test_missing_followup_command_stops_with_explicit_error(self):
        self.titles.write_text("First\nNever run\n")
        self.environment["OMIT_COMMAND"] = "1"
        result = self.run_script(self.titles, self.output)
        self.assertEqual(2, result.returncode)
        self.assertEqual(1, len(self.calls()))
        self.assertIn("No button 2 command found", result.stderr)
        _, saved = self.saved_commands()
        self.assertNotIn("# Collection: First", saved)

    def test_id_mode_passes_pids_and_literal_titles_and_keeps_saved_commands(self):
        self.titles.write_bytes(
            b"81310703090004641\tScarlet & Black (S&B) Archives\r\n"
            b"81310652990004641\tSyllabi and Curricular Materials",
        )
        result = self.run_script("--ids", self.titles, self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls()
        self.assertEqual(2, len(calls))
        for call, pid, title in zip(calls, ("81310703090004641", "81310652990004641"),
                                    ("Scarlet & Black (S&B) Archives", "Syllabi and Curricular Materials")):
            self.assertEqual(pid, call[call.index("--collection-id") + 1])
            self.assertIn(f"--collection-title={title}", call)
        _, saved = self.saved_commands()
        self.assertEqual(2, saved.count("/fake/python -m gems --headless"))
        self.assertIn("# Collection: Scarlet & Black (S&B) Archives", saved)

    def test_id_mode_rejects_bad_rows_and_still_stops_on_retrieval_failure(self):
        for text in ("No tab", "abc\tTitle", "123\t", "\tNo ID", "123\tTitle\tExtra",
                     "collection_id\ttitle"):
            with self.subTest(text=text):
                self.titles.write_text(text)
                result = self.run_script("--ids", self.titles, self.output)
                self.assertEqual(2, result.returncode)
                self.assertIn("line 1", result.stderr)
        self.assertEqual([], self.calls())
        self.titles.write_text("123\tFirst\n456\tFail\n789\tNever run\n")
        result = self.run_script("--ids", self.titles, self.output)
        self.assertEqual(7, result.returncode)
        self.assertEqual(2, len(self.calls()))
        self.assertNotIn("Never run", result.stdout)

    def test_supplied_pid_list_matches_current_titles_and_verified_browser_rows(self):
        root = Path(__file__).parents[1]
        rows = [line.split("\t") for line in (root / "collections.tsv").read_text().splitlines()]
        self.assertTrue(all(len(row) == 2 and row[0].isascii() and row[0].isdecimal() for row in rows))
        self.assertEqual(len(rows), len({row[0] for row in rows}))
        self.assertEqual((root / "collection-titles.txt").read_text().splitlines(), [row[1] for row in rows])

    def test_relative_paths_and_environment_file_precedence(self):
        self.titles.write_text("Title\n")
        inherited = self.root / "inherited.env"
        explicit = self.root / "explicit's config.env"
        inherited.touch()
        explicit.touch()
        self.environment["GEMS_ENV_FILE"] = inherited.name
        for selected in (None, explicit):
            with self.subTest(selected=selected):
                args = [selected.name] if selected else []
                result = self.run_script(self.titles.name, self.output.name, *args)
                self.assertEqual(0, result.returncode, result.stderr)
                call = self.calls()[-1]
                self.assertEqual(str(selected or inherited), call[call.index("--env-file") + 1])

    def test_invalid_inputs_make_no_retrieval_calls(self):
        self.titles.write_text("Title\n")
        cases = [
            (), (self.titles,), (self.root / "missing.txt", self.output),
            (self.titles, self.root / "missing-output"),
            (self.titles, self.output, self.root / "missing.env"),
            (self.titles, self.output, "env", "extra"),
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual([], self.calls())

    def test_empty_title_file_fails_explicitly(self):
        self.titles.write_text("\n \t\n")
        result = self.run_script(self.titles, self.output)
        self.assertEqual(2, result.returncode)
        self.assertIn("No collection titles", result.stderr)
        self.assertEqual([], self.calls())

    def test_missing_virtual_environment_and_help(self):
        self.titles.write_text("Title\n")
        (self.repo / ".venv/bin/python").unlink()
        result = self.run_script(self.titles, self.output)
        self.assertEqual(2, result.returncode)
        self.assertIn("virtual environment is missing", result.stderr)
        result = self.run_script("--help")
        self.assertEqual(0, result.returncode)
        self.assertIn("TITLES_FILE OUTPUT_DIRECTORY", result.stdout)


if __name__ == "__main__":
    unittest.main()
