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
than the key asks for still gets the point when the correct answer is
among the marks.

The run prints, for every question, how many students answered it
correctly and the percentage of those taking the exam, and then lists every blank or multiple-mark answer with the
student, the question, the marked letters and the key, saying whether
the point was given.

### Per-problem results

With `--by-problem` the results file has one column per problem with a
0 or 1, in the order the problems appear in the key, followed by a
`Score` column with the total.  Roster columns are kept, except that
the student identifier is written once, in a column called `SID`.
Randomized variants of one problem, named like `Question1.1_v1` and
`Question1.1_v2`, are reported under the common name `Question1.1`.
