# Grading Tools

Scripts to grade the exams produced by
[exam-writer](https://github.com/SBU-Physics-For-Life-Science/exam-writer)
and, eventually, the whole course.

## exam-grader.py

Grade one exam from the scantron answers.

```
usage: exam-grader.py [-h] [-p] roster key answers results

positional arguments:
  roster            The roster downloaded from blackboard or brightspace (CSV)
  key               The key produced by exam-writer (CSV)
  answers           The exam answers returned from opscan (CSV)
  results           The output file with a score for each student (CSV)

options:
  -h, --help        show this help message and exit
  -p, --by-problem  Also write a 0/1 column per problem to the results
                    (randomized variants such as Question1.1_v2 are combined
                    under Question1.1), and put the total in a 'Score' column
                    instead of the roster's last column
```

- `roster`: the course roster exported from Blackboard or Brightspace.
  The columns `Last Name`, `First Name` and `Student ID` (Blackboard) or
  `OrgDefinedId` (Brightspace) are used to identify each student.
  Without `--by-problem` the score is written into the **last column**
  of the roster if that column is empty for every student; otherwise a
  `Score` column is appended, so the student identifier is never
  overwritten.
- `key`: the `<basename>-keys.csv` file written by `exam-writer.py`.
  Students are matched to their exam copy by student ID.
- `answers`: the CSV returned by the scanning centre, with the columns
  `LAST NAME`, `FIRST NAME`, `STUDENT ID` and one column per question
  numbered `1`, `2`, ...  Header lines above the column names must be
  removed by hand first.  Every student ID in this file must be on the
  roster, otherwise the script stops and lists the unknown IDs; remove
  the scanning centre's test sheet (ID `9999999999`, name `ZZZ`) too.
- `results`: the output CSV.  It is never overwritten; delete it first to
  grade again.  A bar chart of the score distribution is saved next to
  it with the same name and a `.png` ending (requires matplotlib).
  Scores of zero are left out and the mean of the rest is drawn as a
  dashed line and given in the legend, also as a percentage of the
  maximum score.

A question whose key is in upper case (`ABC`) is correct if the student
marked all of those letters.  A key in lower case (`abc`, which
exam-writer uses when several answers are correct) is correct if any of
the marked letters is among them.  A student who marks more letters
than the key asks for gets no point from the script, even when the
correct answer is among the marks.

The run prints, for every question, how many students answered it
correctly and the percentage of those taking the exam, and then lists
every blank or multiple-mark answer with the student, the question, the
marked letters and the key.  For a multiple mark it says whether the
correct answer is among the marks or none of them is correct, so the
professor can decide by hand whether to give the point.

### Per-problem results

With `--by-problem` the results file has one column per problem with a
0 or 1, in the order the problems appear in the key, followed by a
`Score` column with the total.  Roster columns are kept, except that
the student identifier is written once, in a column called `SID`.
Randomized variants of one problem, named like `Question1.1_v1` and
`Question1.1_v2`, are reported under the common name `Question1.1`.

## course-grader.py

Combine the scores of all the categories of a course (exams, lab,
homework, clickers, extra credit, ...) into a total and a letter grade
for every student on the roster.  Everything is described in a YAML
file; `course-grader-example.yaml` is a documented example.

```
usage: course-grader.py [-h] [-s WHO] [-n] config

positional arguments:
  config             The YAML configuration file

options:
  -h, --help         show this help message and exit
  -s, --student WHO  Print a detailed breakdown for one student, given by id
                     or as 'Last, First' (may be repeated)
  -n, --dry-run      Compute and print the summary but write no files
```

The configuration gives the roster, the output files, the letter
scale and, for every category, its weight, the CSV with the scores,
which column(s) hold them and their maximum, how the file names the
students (id, name or email), and how many of the lowest scores to
drop.  Score files are read as they come from the scanning centre,
Pearson, Vevox or `exam-grader.py`: the header row is found
automatically and Pearson's "Assigned Points:" row can supply the
maxima.  Students are matched by id when the file has one, otherwise
by name; `aliases` map a student to a different name used in a file.

The score of a category is the average, in percent, of its items
after the drops.  The total is the sum of score × weight; the weights
of extra-credit categories add on top of 100.  A student missing from
a file gets 0 in that category and is listed in the printout, as are
the rows of a file that match nobody on the roster.

`exceptions` adjust single students: exclude a category and move its
weight to the other categories (all of them in proportion to their
weights, or only those named), drop more lowest scores, leave out
particular items such as the clicker questions of a missed lecture,
set a score by hand, or force a letter grade.  Every exception carries a note
that is copied to the results.

The results file repeats the roster columns and adds the score and the
weight of every category, the total with and without extra credit, the
letter and the notes.  A histogram of the totals with the letter
bounds can also be written.  PyYAML is used when installed; otherwise
a small built-in reader handles the configuration.
