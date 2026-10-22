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
            'done\n',
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

    def test_failure_stops_immediately_and_preserves_exit_status(self):
        self.titles.write_text("First\nFail\nNever run\n")
        result = self.run_script(self.titles, self.output)
        self.assertEqual(7, result.returncode)
        self.assertEqual(2, len(self.calls()))
        self.assertIn("Stopped at line 2: Fail", result.stderr)
        self.assertIn("Completed 1 collection(s)", result.stderr)
        self.assertNotIn("Never run", result.stdout)

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
