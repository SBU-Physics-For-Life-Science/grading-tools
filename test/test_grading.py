#!/usr/bin/env python3
#
# Tests of exam-grader.py and course-grader.py on the mock files in
# test/data.  Run from the top of the repository with
#
#     python3 -m unittest discover test
#
# or simply "python3 test/test_grading.py".  Only the standard library
# is needed; the checks of the plots are skipped without matplotlib.
#
# Every test copies test/data to a temporary folder and runs the
# scripts there, so nothing is written to the repository.
#
# The mock exam has four questions; the key of every student is
#     A ; BC ; ab ; D        (Carl has the variant Question1.1_v2, key C)
# "BC" (upper case) needs both B and C, "ab" (lower case) accepts A or B
# but only one mark.  The answers give:
#     Ann   A  BC  B   D     4  everything right
#     Bob   A  B   AB  -     1  BC needs C too; two marks on "ab"
#                               (flagged); question 4 blank (flagged)
#     Carl  B  CB  a   D     3  the key of his variant is C; the
#                               order of the marks does not matter;
#                               lower case answers are accepted
#     Dana  (no sheet)       0  not counted among those taking the exam
#     Eve   A  ABC E   D     2  three marks on BC (flagged, no point)

import csv
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXAM_GRADER = os.path.join(HERE, "..", "exam-grader.py")
COURSE_GRADER = os.path.join(HERE, "..", "course-grader.py")
HAVE_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None

ANN, BOB, CARL, DANA, EVE = ("100000001", "100000002", "100000003",
                             "100000004", "100000005")


def ReadCsv(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


class Workspace(unittest.TestCase):
    # A temporary copy of test/data for every test.
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="grading-test-")
        for name in os.listdir(DATA):
            shutil.copy(os.path.join(DATA, name), self.dir)
        env = dict(os.environ)
        env["MPLBACKEND"] = "Agg"
        self.env = env

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def File(self, name):
        return os.path.join(self.dir, name)

    def Run(self, script, *args, check=True):
        proc = subprocess.run([sys.executable, script] + list(args),
                              cwd=self.dir, env=self.env,
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            self.fail("%s failed (exit %d)\nSTDOUT:\n%s\nSTDERR:\n%s" % (
                os.path.basename(script), proc.returncode,
                proc.stdout, proc.stderr))
        return proc

    def Exam(self, *args, check=True):
        return self.Run(EXAM_GRADER, *args, check=check)

    def Course(self, *args, check=True):
        return self.Run(COURSE_GRADER, *args, check=check)


###########################################################
class TestExamGrader(Workspace):
    EXPECTED = {ANN: 4, BOB: 1, CARL: 3, DANA: 0, EVE: 2}

    def test_score_column_added(self):
        # The last roster column (Section) is not empty: it must be kept
        # and the score written to an added "Score" column.
        out = self.Exam("roster.csv", "exam-keys.csv", "exam-answers.csv",
                        "results.csv")
        fields, rows = ReadCsv(self.File("results.csv"))
        self.assertEqual(fields, ["OrgDefinedId", "Username", "Last Name",
                                  "First Name", "Section", "Score"])
        self.assertEqual([r["Section"] for r in rows], ["1", "1", "2", "2", "2"])
        self.assertEqual({r["OrgDefinedId"]: int(r["Score"]) for r in rows},
                         self.EXPECTED)
        # Per-question summary: 4 students took the exam.
        self.assertIn("Total students taking exam 4", out.stdout)
        self.assertIn("Correct responses to  Question1.1 3 (75.0%)", out.stdout)
        self.assertIn("Correct responses to  Question1.2 2 (50.0%)", out.stdout)
        self.assertIn("Correct responses to  Question1.3 2 (50.0%)", out.stdout)
        self.assertIn("Correct responses to  Question1.4 3 (75.0%)", out.stdout)
        if HAVE_MATPLOTLIB:
            self.assertTrue(os.path.exists(self.File("results.png")))

    def test_by_problem(self):
        self.Exam("-p", "roster.csv", "exam-keys.csv", "exam-answers.csv",
                  "results.csv")
        fields, rows = ReadCsv(self.File("results.csv"))
        # Variants combined under Question1.1; one SID column; Score last.
        self.assertEqual(fields, ["OrgDefinedId", "Username", "Last Name",
                                  "First Name", "Section", "SID",
                                  "Question1.1", "Question1.2",
                                  "Question1.3", "Question1.4", "Score"])
        got = {r["SID"]: [int(r["Question1.%d" % i]) for i in range(1, 5)]
               for r in rows}
        self.assertEqual(got, {ANN:  [1, 1, 1, 1],
                               BOB:  [1, 0, 0, 0],
                               CARL: [0, 1, 1, 1],
                               DANA: [0, 0, 0, 0],
                               EVE:  [1, 0, 0, 1]})
        for r in rows:
            self.assertEqual(int(r["Score"]), sum(got[r["SID"]]))

    def test_blank_and_multiple_marks_reported(self):
        out = self.Exam("roster.csv", "exam-keys.csv", "exam-answers.csv",
                        "results.csv").stdout
        self.assertIn("BLANK OR MULTIPLE-MARK ANSWERS", out)
        self.assertIn("Beta Bob 100000002 Question1.3 marked AB key ab"
                      " (the correct answer is among the marks)", out)
        self.assertIn("Beta Bob 100000002 Question1.4 marked blank key D", out)
        self.assertIn("Epsilon Eve 100000005 Question1.2 marked ABC key BC"
                      " (the correct answer is among the marks)", out)
        self.assertIn("Sheets with problems 2 questions with problems 3"
                      " multiple marks that include the key 2", out)

    def test_unknown_student_id_stops(self):
        with open(self.File("exam-answers.csv"), "a") as f:
            f.write("ZZZ,TEST,9999999999,A,BC,A,D\n")
        proc = self.Exam("roster.csv", "exam-keys.csv", "exam-answers.csv",
                         "results.csv", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("STUDENT ID IN ANSWERS NOT FOUND IN ROSTER", proc.stdout)
        self.assertIn("9999999999", proc.stdout)
        self.assertFalse(os.path.exists(self.File("results.csv")))

    def test_results_never_overwritten(self):
        with open(self.File("results.csv"), "w") as f:
            f.write("keep me\n")
        proc = self.Exam("roster.csv", "exam-keys.csv", "exam-answers.csv",
                         "results.csv", check=False)
        self.assertNotEqual(proc.returncode, 0)
        with open(self.File("results.csv")) as f:
            self.assertEqual(f.read(), "keep me\n")


###########################################################
# Expected course grades (weights: midterm 30, homework 30, lab 40,
# bonus 5 extra credit; letters A 90, B 80, C 70, D 60, F 0 after
# rounding the total half up to an integer):
#
#   Ann   midterm 100  hw 100 (section 1, drop 1)  lab 90  bonus 100
#         total 30 + 30 + 36 + 5 = 101, without bonus 96          A
#   Bob   midterm excluded: its 30 goes to hw and lab as 30:40, so the
#         weights are 0, 42.8571, 57.1429.  hw (as "Beta, Robert")
#         50, 0, 50 -> drop the 0 -> 50.  lab 60.  no bonus.
#         total 50*0.428571 + 60*0.571429 = 55.7143                  F
#   Carl  midterm 75  hw 80, 60, 100 -> 80 (section 2, no drop)
#         lab 70  bonus 50
#         total 22.5 + 24 + 28 + 2.5 = 77, without bonus 74.5
#         letter forced to                                           I
#   Dana  midterm 0 (no sheet)  hw 100, "--" (not assigned, ignored),
#         50 -> 75  lab set by hand to 92  no bonus
#         total 0 + 22.5 + 36.8 = 59.3 -> 59                         F
#         (within 0.5 of a D: needs 59.5 - 59.3 = 0.2)
#   Eve   midterm 50  hw 100, 100, (HW 3 dropped by exception) -> 100
#         lab 86.25  no bonus
#         total 15 + 30 + 34.5 = 79.5 -> rounds half up to 80        B
class TestCourseGrader(Workspace):
    def setUp(self):
        super().setUp()
        # The midterm scores come from exam-grader.py itself.
        self.Exam("-p", "roster.csv", "exam-keys.csv", "exam-answers.csv",
                  "midterm-results.csv")

    def Grades(self):
        fields, rows = ReadCsv(self.File("grades.csv"))
        return fields, {r["OrgDefinedId"]: r for r in rows}

    def test_output_columns(self):
        self.Course("course.yaml")
        fields, rows = self.Grades()
        self.assertEqual(fields, [
            "OrgDefinedId", "Username", "Last Name", "First Name", "Section",
            "midterm", "homework", "lab", "bonus",
            "weight midterm", "weight homework", "weight lab", "weight bonus",
            "Total", "Total w/o extra credit", "Letter", "Notes"])
        self.assertEqual(sorted(rows), [ANN, BOB, CARL, DANA, EVE])

    def test_category_scores(self):
        self.Course("course.yaml")
        fields, rows = self.Grades()
        expected = {ANN:  (100, 100, 90, 100),
                    BOB:  (25, 50, 60, 0),
                    CARL: (75, 80, 70, 50),
                    DANA: (0, 75, 92, 0),
                    EVE:  (50, 100, 86.25, 0)}
        for sid, scores in expected.items():
            for c, v in zip(("midterm", "homework", "lab", "bonus"), scores):
                self.assertAlmostEqual(float(rows[sid][c]), v, places=2,
                                       msg="%s %s" % (sid, c))

    def test_weights_and_redistribution(self):
        self.Course("course.yaml")
        fields, rows = self.Grades()
        for sid in (ANN, CARL, DANA, EVE):
            self.assertEqual([rows[sid]["weight " + c] for c in
                              ("midterm", "homework", "lab", "bonus")],
                             ["30", "30", "40", "5"])
        bob = rows[BOB]
        self.assertEqual(float(bob["weight midterm"]), 0)
        self.assertAlmostEqual(float(bob["weight homework"]), 300/7, places=3)
        self.assertAlmostEqual(float(bob["weight lab"]), 400/7, places=3)
        self.assertEqual(float(bob["weight bonus"]), 5)

    def test_totals_and_letters(self):
        self.Course("course.yaml")
        fields, rows = self.Grades()
        expected = {ANN:  (101.00, 96.00, "A"),
                    BOB:  (55.71, 55.71, "F"),
                    CARL: (77.00, 74.50, "I"),
                    DANA: (59.30, 59.30, "F"),
                    EVE:  (79.50, 79.50, "B")}
        for sid, (total, noBonus, letter) in expected.items():
            r = rows[sid]
            self.assertAlmostEqual(float(r["Total"]), total, places=2, msg=sid)
            self.assertAlmostEqual(float(r["Total w/o extra credit"]), noBonus,
                                   places=2, msg=sid)
            self.assertEqual(r["Letter"], letter, msg=sid)

    def test_notes(self):
        self.Course("course.yaml")
        fields, rows = self.Grades()
        self.assertEqual(rows[ANN]["Notes"], "")
        self.assertEqual(rows[BOB]["Notes"], "Missed the midterm")
        self.assertEqual(rows[CARL]["Notes"], "Incomplete")
        self.assertEqual(rows[DANA]["Notes"], "Lab corrected")
        self.assertEqual(rows[EVE]["Notes"], "HW 3 excused")

    def test_summary_printout(self):
        out = self.Course("course.yaml").stdout
        self.assertIn("Students on roster 5", out)
        # Lines above the Pearson header skipped, the points row read.
        self.assertIn("homework [1]", out)
        # The extra row of the lab file and the students without bonus.
        self.assertIn("lab: 1 row of lab.csv match nobody on the roster", out)
        self.assertIn("Nobody Zed", out)
        self.assertIn("bonus: 3 roster students not in the file", out)
        # exam-grader.py writes every roster student, so none is missing.
        self.assertNotIn("midterm: ", out)
        # Means and letter counts for all and per section.
        self.assertRegex(out, r"total\s+74\.50\s+78\.36\s+71\.93")
        self.assertRegex(out, r"letter grades: A 1\s+B 1\s+F 2\s+I 1")
        self.assertRegex(out, r"letter grades section 01: A 1\s+F 1")
        self.assertRegex(out, r"letter grades section 02: B 1\s+F 1\s+I 1")
        self.assertIn("4 students with exceptions", out)
        # Dana is 0.2 from a D; Carl's letter is forced, so not listed.
        self.assertIn("STUDENTS WITHIN 0.5 OF A HIGHER LETTER: 1", out)
        self.assertRegex(out, r"Delta Dana\s+100000004\s+total\s+59\.30\s+"
                              r"F\s+->\s+D\s+needs \+0\.20")

    def test_student_breakdown(self):
        out = self.Course("-n", "-s", "Beta, Bob", "course.yaml").stdout
        self.assertIn("Beta Bob  id 100000002", out)
        self.assertIn("note: Missed the midterm", out)
        self.assertRegex(out, r"midterm\s+score\s+25\.00%\s+weight\s+0\.00%"
                              r".*\(excluded\)")
        self.assertRegex(out, r"HW 2\s+0\.00 / 10\s+=\s+0\.00%\s+dropped")
        self.assertIn("total 55.71 (without extra credit 55.71)  letter F", out)

    def test_dry_run_writes_nothing(self):
        out = self.Course("-n", "course.yaml").stdout
        self.assertIn("Dry run: no files written", out)
        self.assertFalse(os.path.exists(self.File("grades.csv")))
        self.assertFalse(os.path.exists(self.File("plots")))

    @unittest.skipUnless(HAVE_MATPLOTLIB, "matplotlib is not installed")
    def test_plots(self):
        self.Course("course.yaml")
        names = set(os.listdir(self.File("plots")))
        for name in ("total.png", "total-cumulative.png", "lettergrades.png",
                     "midterm.png", "homework.png", "lab.png", "bonus.png",
                     "homework-items.png", "scatter-homework-lab.png"):
            self.assertIn("t_" + name, names)
        # Categories with a single column get no item plot.
        self.assertNotIn("t_midterm-items.png", names)

    def test_rounding_off_changes_letter(self):
        # Without rounding Eve's 79.5 stays a C.
        path = self.File("course.yaml")
        with open(path) as f: text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("round_digits: 0\n", ""))
        self.Course("course.yaml")
        fields, rows = self.Grades()
        self.assertEqual(rows[EVE]["Letter"], "C")

    def test_bad_redistribution_is_rejected(self):
        # Explicit weights that do not add up to 100 must stop the run.
        path = self.File("course.yaml")
        with open(path) as f: text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("    exclude: [midterm]\n",
                                 "    exclude: [midterm]\n"
                                 "    redistribute: {homework: 40, lab: 40}\n"))
        proc = self.Course("course.yaml", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("add up to 80, not 100", proc.stdout + proc.stderr)

    def test_explicit_redistribution(self):
        path = self.File("course.yaml")
        with open(path) as f: text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("    exclude: [midterm]\n",
                                 "    exclude: [midterm]\n"
                                 "    redistribute: {homework: 50, lab: 50}\n"))
        self.Course("course.yaml")
        fields, rows = self.Grades()
        bob = rows[BOB]
        self.assertEqual(bob["weight homework"], "50")
        self.assertEqual(bob["weight lab"], "50")
        self.assertAlmostEqual(float(bob["Total"]), 55.0, places=2)  # 25 + 30


if __name__ == "__main__":
    unittest.main()
