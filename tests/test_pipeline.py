"""Offline tests: no network, no API keys. Run with:  python -m unittest discover -s tests -v"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "sponsors"))
sys.path.insert(0, str(ROOT / "pipeline" / "screening"))
sys.path.insert(0, str(ROOT / "pipeline" / "tailoring"))

import sponsor_check  # noqa: E402
import prefilter  # noqa: E402
import check  # noqa: E402


class SponsorNames(unittest.TestCase):
    def test_suffixes_and_punctuation_are_ignored(self):
        self.assertEqual(sponsor_check.normalise_name("Example Health Trust Ltd"), "example health trust")
        self.assertEqual(sponsor_check.normalise_name("Contoso Retail Limited"),
                         sponsor_check.normalise_name("CONTOSO RETAIL LTD."))


class PreFilter(unittest.TestCase):
    def run_prefilter(self):
        out = Path(tempfile.mkdtemp()) / "out.csv"
        subprocess.run([sys.executable, str(ROOT / "pipeline/screening/prefilter.py"),
                        str(ROOT / "examples/jobs.example.csv"),
                        str(ROOT / "examples/register_a_rated.example.csv"), str(out)],
                       check=True, capture_output=True)
        return list(csv.DictReader(open(out, encoding="utf-8")))

    def test_reasons(self):
        rows = self.run_prefilter()
        reasons = [r["prefilter_reason"] or "keep" for r in rows]
        self.assertEqual(reasons[0], "keep")
        self.assertEqual(reasons[1], "seniority")
        self.assertTrue(reasons[2].startswith("salary below floor"))
        self.assertEqual(reasons[3], "no sponsorship")
        self.assertEqual(reasons[4], "duplicate")   # same link once tracking params are stripped

    def test_salary_parsing(self):
        self.assertEqual(prefilter.top_salary("£38,000 - £44,000"), 44000)
        self.assertEqual(prefilter.top_salary("up to £45k"), 45000)
        self.assertIsNone(prefilter.top_salary("competitive"))


class CvChecks(unittest.TestCase):
    def test_example_passes_and_banned_words_fail(self):
        ex = ROOT / "examples"
        rules = str(ex / "check_rules.example.json")
        res = check.run(str(ex / "cv.example.json"), str(ex / "cover_letter.example.txt"),
                        str(ex / "job_description.example.txt"), "missing.pdf", rules)
        self.assertEqual(res["banned"], [])
        bad = Path(tempfile.mkdtemp()) / "letter.txt"
        bad.write_text("I am a passionate team player with Databricks experience.")
        res = check.run(str(ex / "cv.example.json"), str(bad), str(ex / "job_description.example.txt"),
                        "missing.pdf", rules)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["banned"]), 3)


if __name__ == "__main__":
    unittest.main()
