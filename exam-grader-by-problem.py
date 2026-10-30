#!/usr/bin/env python3

import csv
import string
import argparse
import os.path
import sys
import io

parser = argparse.ArgumentParser(
    description="Grade an exam read from the scantron sheets")
parser.add_argument("roster",nargs=1,action="store",
                    help="The roster downloaded from blackboard or brightspace (CSV)")
parser.add_argument("key",nargs=1,action="store",
                    help="The key produced by exam-writer (CSV)")
parser.add_argument("answers",nargs=1,action="store",
                    help="The exam answers returned from opscan (CSV)")
parser.add_argument("results",nargs=1,action="store",
                    help="The output file with a score for each student (CSV)")
options = parser.parse_args()

###########################################################3
# Read a Black Board roster and fill a dictionary with "LASTNAME",
# "FIRSTNAME", and "SID" (student identification number).  This also
# saves a copy of the roster so that the output results can be added.
# The roster should be downloaded so that the last column is empty and
# will hold the score.
class ExamRoster:
    def __init__(self):
        self.student = list()
        self.roster = list()
        self.fields = list()
        
    def ReadFile(self,rosterFile):
        try:
            with io.open(rosterFile,"r",encoding="ascii",errors="ignore") as f:
                reader = csv.DictReader(f)
                # Save the original roster columns before adding grading results.
                # Drop completely unnamed columns from the exported roster.
                self.fields = [k for k in reader.fieldnames if k is not None and k.strip() != ""]
                count = 0
                for v in reader:
                    ## Create the output list (elements are over-written)
                    out = dict()
                    for k in v:
                        if "Last Name" in k: out["LASTNAME"] = v[k]
                        if "First Name" in k: out["FIRSTNAME"] = v[k]
                        # next line matchs BlackBoard student id field
                        if "Student ID" in k: out["SID"] = v[k]
                        # next line matchs BrightSpace student id field
                        if "OrgDefinedId" in k: out["SID"] = v[k]
                    print("ROSTER ", out["LASTNAME"], out["FIRSTNAME"], out["SID"])
                    count = count+1
                    self.student.append(out)
                    self.roster.append(v)
                print("Students on roster",count)
        except:
            print ("Problem reading roster")
            raise RuntimeError("Roster parsing error")

###########################################################3
# Read an answer key from exam-writer.py and fill a dictionary with
# "LASTNAME", "FIRSTNAME", "SID" (student identification number), and
# a list with the expected answers for the student.
class ExamKey:
    def __init__(self):
        self.student = list()
        
    def ReadFile(self,keyFile):
        try:
            print(keyFile)
            with io.open(keyFile,"r",encoding="ascii",errors="ignore") as f:
                reader = csv.DictReader(f)
                count = 0
                for v in reader:
                    out = dict()
                    out["LASTNAME"] = v["LASTNAME"]
                    out["FIRSTNAME"] = v["FIRSTNAME"]
                    out["SID"] = v["SID"]
                    out["Answers"] = v["Answers"].split(';')
                    out["QuestionNames"] = v["QuestionNames"].split(';')
                    print("KEYS ", out["LASTNAME"], out["FIRSTNAME"], out["SID"])
                    count = count + 1
                    self.student.append(out)
                print("lines in key",count)
        except:
            print ("Problem reading key")
            raise RuntimeError("Key parsing error")

    def GetKey(self,sid,lastname,firstname):
        for v in self.student:
            if sid == v["SID"]:
                return v
        print("No matching key", sid)
        return None

###########################################################3
# Read an response file from the opscan center and fill a dictionary
# with "LASTNAME", "FIRSTNAME", "SID" (student identification number),
# and a list with the provided answers for the student.  This may need
# to be updated as the results format changes.  Check the file and
# make the needed changes.
#
# NOTE: The scan file often includes header lines that need to be
# skipped.  The best way is to use an editor by hand.
class ExamAnswers:
    def __init__(self):
        self.student = list()
    
    def ReadFile(self,answerFile):
        try:
            print(answerFile)
            with io.open(answerFile,"r",encoding="ascii",errors="ignore") as f:
                reader = csv.DictReader(f)
                for v in reader:
                    out = dict()
                    out["LASTNAME"] = v["LAST NAME"]
                    out["FIRSTNAME"] = v["FIRST NAME"]
                    out["SID"] = v["STUDENT ID"]
                    out["Answers"] = list()
                    try: 
                        for i in range(1,1000):
                            out["Answers"].append(v[str(i)].strip())
                    except:
                        pass
                    self.student.append(out)
                    
                        
        except:
            print ("Problem reading answers")
            raise RuntimeError("Answer parsing error")

    def GetAnswers(self,sid,lastname,firstname):
        for v in self.student:
            if sid == v["SID"]:
                return v
        print("No matching answers", lastname, firstname, sid)
        return None

# Score the exam.  There are two cases.  If the key is upper case,
# then the answer needs to exactly match the key ("ABC" must equal
# "ABC").  If the key is lower case, then the answer must be inside
# the key (B is inside "abc" so it's correct).
def CanonicalQuestionName(question):
    # Combine randomized variants of the same underlying problem.
    # Example: AltQuestion1.1_v1 and AltQuestion1.1_v2 -> AltQuestion1.1
    if "_v" in question:
        base, version = question.rsplit("_v", 1)
        if version.isdigit():
            return base
    return question


def ScoreExam(key,answers,summary):
    # Return both the total score and a per-problem 0/1 result dictionary.
    question_results = {
        CanonicalQuestionName(q): 0 for q in key["QuestionNames"]
    }
    if answers is None:
        return 0, question_results

    summary["TOTAL"] = summary["TOTAL"] + 1
    score = 0
    for zz in zip(key["Answers"], answers["Answers"], key["QuestionNames"]):
        answer = zz[1].replace(" ", "").upper()
        expected = zz[0].replace(" ", "")
        question = CanonicalQuestionName(zz[2])
        correct = False

        if expected == expected.lower():
            # Implement "or" for lower case answers in the key.
            for aa in answer:
                if aa in expected.upper():
                    correct = True
                    break
        else:
            # Implement "and" for upper case answers in the key.
            if expected.upper() == answer:
                correct = True

        if correct:
            score += 1
            question_results[question] = 1
            if question not in summary:
                summary[question] = 0
            summary[question] += 1

    return score, question_results

####################################################################
# The main code begins here.

print("Hello world from exam-grader")

# Read the roster to grade.
roster = ExamRoster()
roster.ReadFile(options.roster[0])

# Read the key for the exam
keys = ExamKey()
keys.ReadFile(options.key[0])

# Read the answers for each student to the exam
answers = ExamAnswers()
answers.ReadFile(options.answers[0])

summary = dict()
summary['TOTAL'] = 0
for student, entry in zip(roster.student,roster.roster):
    key = keys.GetKey(student["SID"],student["LASTNAME"],student["FIRSTNAME"])
    if key is None:
        print (student["SID"],student["LASTNAME"],student["FIRSTNAME"])
        raise RuntimeError("Missing key")
    answer = answers.GetAnswers(student["SID"],
                                student["LASTNAME"],
                                student["FIRSTNAME"])
    score, question_results = ScoreExam(key,answer,summary)

    # Add the 0/1 result for each question. The original roster student-ID column is preserved.
    for question, result in question_results.items():
        entry[question] = str(result)

    # Never overwrite a roster field: put the total in an explicit Score column.
    entry["Score"] = str(score)

res = {key: val
       for key, val in sorted(summary.items(), key = lambda ele: ele[0])}

print("SUMMARY OF EXAM RESPONSES")
for q in res:
    if q == "TOTAL": pass
    print("      Correct responses to ", q,summary[q])
print("   Total students taking exam",summary["TOTAL"])

# Build a clean common set of CSV columns for all personalized exams.
# Do not trust the roster's Student ID / SID / blank trailing columns for output:
# student["SID"] is the identifier actually used successfully for matching.
question_fields = []
for key_entry in keys.student:
    for question in key_entry["QuestionNames"]:
        question = CanonicalQuestionName(question)
        if question not in question_fields:
            question_fields.append(question)

# Preserve ordinary roster metadata, but explicitly remove identifier aliases,
# blank columns, old score placeholders, and any pre-existing grading columns.
excluded = set(question_fields) | {"Student ID", "SID", "Score"}
base_fields = [
    f for f in roster.fields
    if f is not None and f.strip() != "" and f not in excluded
]

# Keep exactly ONE identifier column in the output.
fields = base_fields + ["SID"] + question_fields + ["Score"]

try:
    with open(options.results[0], "x", newline="") as f:
        output = csv.DictWriter(f, fields)
        output.writeheader()
        for student, row in zip(roster.student, roster.roster):
            clean_row = {field: row.get(field, "") for field in base_fields}
            clean_row["SID"] = student["SID"]
            for question in question_fields:
                clean_row[question] = row.get(question, "")
            clean_row["Score"] = row.get("Score", "")
            output.writerow(clean_row)
except:
    raise RuntimeError("Bad result write")
