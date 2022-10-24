#!/usr/bin/env python3

import csv
import string
import argparse
import os.path
import sys

parser = argparse.ArgumentParser(
    description="Grade an exam read from the scantron sheets")
parser.add_argument("roster",nargs=1,action="store")
parser.add_argument("key",nargs=1,action="store")
parser.add_argument("answers",nargs=1,action="store")
parser.add_argument("results",nargs=1,action="store")
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
        
    def ReadFile(self,rosterFile):
        try:
            with open(rosterFile,"r") as f:
                reader = csv.DictReader(f)
                for v in reader:
                    ## Create the output list (elements are over-written)
                    out = dict()
                    for k in v:
                        if "Last Name" in k: out["LASTNAME"] = v[k]
                        if "First Name" in k: out["FIRSTNAME"] = v[k]
                        if "Student ID" in k: out["SID"] = v[k]
                    self.student.append(out)
                    self.roster.append(v)
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
            with open(keyFile,"r") as f:
                reader = csv.DictReader(f)
                for v in reader:
                    out = dict()
                    out["LASTNAME"] = v["LASTNAME"]
                    out["FIRSTNAME"] = v["FIRSTNAME"]
                    out["SID"] = v["SID"]
                    out["Answers"] = v["Answers"].split(';')
                    self.student.append(out)
                        
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
class ExamAnswers:
    def __init__(self):
        self.student = list()
    
    def ReadFile(self,answerFile):
        try:
            print(answerFile)
            with open(answerFile,"r") as f:
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
        print("No matching answers", sid)
        return None

def ScoreExam(key,answers):
    if answers is None: return 0
    score = 0
    for a in zip(key["Answers"],answers["Answers"]):
        if a[0] == a[1]: score = score + 1
    return score
    
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

for student, entry in zip(roster.student,roster.roster):
    key = keys.GetKey(student["SID"],student["LASTNAME"],student["FIRSTNAME"])
    if key is None: raise RuntimeError("Missing key")
    answer = answers.GetAnswers(student["SID"],
                                student["LASTNAME"],
                                student["FIRSTNAME"])
    lastKey = list(entry.keys())[-1]
    score = ScoreExam(key,answer)
    entry[lastKey] = str(score)

fields = list(roster.roster[0].keys())

try:
    with open(options.results[0],"x") as f:
        output = csv.DictWriter(f,fields)
        output.writeheader()
        for row in roster.roster:
            output.writerow(row)
except:
    raise RuntimeError("Bad result write")
