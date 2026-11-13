#!/usr/bin/env python3
#
# Combine the scores of the categories of a course (exams, homework,
# clickers, lab, ...) into a total and a letter grade for every student
# on the roster.  Everything is driven by a YAML configuration file;
# see course-grader-example.yaml and the README for the format.
#
# The configuration gives, for every category, a weight and a CSV file
# with the scores, how the students in that file are identified (by id
# or by name), which column(s) hold the scores and their maximum, and
# how many of the lowest scores to drop.  Exceptions for single
# students can exclude a category (its weight is moved to the other
# categories), drop more scores, set a score by hand, or force a letter
# grade.

import argparse
import csv
import fnmatch
import io
import math
import os.path
import re
import sys

parser = argparse.ArgumentParser(
    description="Combine the category scores of a course into total grades")
parser.add_argument("config", nargs=1, action="store",
                    help="The YAML configuration file")
parser.add_argument("-s", "--student", dest="students", action="append",
                    default=[], metavar="WHO",
                    help="Print a detailed breakdown for one student, given"
                    " by id or as 'Last, First' (may be repeated)")
parser.add_argument("-n", "--dry-run", dest="dryRun", action="store_true",
                    default=False,
                    help="Compute and print the summary but write no files")
options = parser.parse_args()

###########################################################
# A tiny YAML reader, used only if PyYAML is not installed.  It reads
# the subset of YAML that the configuration needs: nested mappings
# and lists by indentation, inline [lists] and {mappings}, quoted or
# plain scalars, numbers, true/false/null, and "#" comments.
def StripComment(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote: quote = None
        elif c in "\"'": quote = c
        elif c == "#" and (i == 0 or line[i-1] in " \t"): return line[:i]
    return line

def SplitFlow(text):
    # Split "a, b, [c, d], {e: f}" on the commas at depth zero.
    items, depth, quote, current = [], 0, None, ""
    for c in text:
        if quote:
            current += c
            if c == quote: quote = None
        elif c in "\"'": quote = c; current += c
        elif c in "[{": depth += 1; current += c
        elif c in "]}": depth -= 1; current += c
        elif c == "," and depth == 0: items.append(current); current = ""
        else: current += c
    if current.strip(): items.append(current)
    return [i.strip() for i in items]

def SplitKey(text):
    # Split "key: value" at the first ": " (or a trailing ":").
    quote = None
    for i, c in enumerate(text):
        if quote:
            if c == quote: quote = None
        elif c in "\"'": quote = c
        elif c == ":" and (i+1 == len(text) or text[i+1] in " \t"):
            return ParseScalar(text[:i].strip()), text[i+1:].strip()
    return None, None

def ParseScalar(text):
    if text == "" or text in ("null", "~"): return None
    if text[0] in "\"'" and text[-1] == text[0] and len(text) > 1:
        return text[1:-1]
    if text[0] == "[" and text[-1] == "]":
        return [ParseScalar(i) for i in SplitFlow(text[1:-1])]
    if text[0] == "{" and text[-1] == "}":
        out = dict()
        for item in SplitFlow(text[1:-1]):
            key, value = SplitKey(item)
            out[key] = ParseScalar(value)
        return out
    if text in ("true", "True", "yes"): return True
    if text in ("false", "False", "no"): return False
    try: return int(text)
    except ValueError: pass
    try: return float(text)
    except ValueError: pass
    return text

def ParseBlock(lines, pos, indent):
    # lines is a list of (indent, text); returns (value, next position).
    if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
        out = list()
        while pos < len(lines) and lines[pos][0] == indent \
                and (lines[pos][1].startswith("- ") or lines[pos][1] == "-"):
            item = lines[pos][1][1:].strip()
            if item == "":
                value, pos = ParseBlock(lines, pos+1, lines[pos+1][0])
            else:
                key, rest = SplitKey(item)
                if key is not None and item[0] not in "[{\"'":
                    # A mapping that starts on the dash line.
                    lines[pos] = (indent+2, item)
                    value, pos = ParseBlock(lines, pos, indent+2)
                else:
                    value = ParseScalar(item); pos += 1
            out.append(value)
        return out, pos
    out = dict()
    while pos < len(lines) and lines[pos][0] == indent \
            and not lines[pos][1].startswith("- "):
        key, rest = SplitKey(lines[pos][1])
        if key is None:
            raise RuntimeError("Cannot read configuration line: %s"
                               % lines[pos][1])
        pos += 1
        if rest == "":
            if pos < len(lines) and (lines[pos][0] > indent or (
                    lines[pos][0] == indent and lines[pos][1].startswith("- "))):
                value, pos = ParseBlock(lines, pos, lines[pos][0])
            else:
                value = None
        else:
            value = ParseScalar(rest)
        out[key] = value
    return out, pos

def LoadYaml(path):
    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    lines = list()
    for raw in text.splitlines():
        line = StripComment(raw.replace("\t", "    ")).rstrip()
        if line.strip() == "" or line.strip() == "---": continue
        lines.append((len(line) - len(line.lstrip(" ")), line.strip()))
    if not lines: return dict()
    value, pos = ParseBlock(lines, 0, lines[0][0])
    if pos != len(lines):
        raise RuntimeError("Cannot read configuration line: %s"
                           % lines[pos][1])
    return value

###########################################################
# Helpers to identify students in the files.  Files may name a student
# by id (Blackboard "Student ID", Brightspace "OrgDefinedId", the
# opscan "STUDENT ID", ...), by first and last name, or by an email of
# the form First.Last@stonybrook.edu.
ID_COLUMNS = ["OrgDefinedId", "Student ID", "STUDENT ID", "SID",
              "Student Id", "StudentID", "ID"]
LAST_COLUMNS = ["Last Name", "LAST NAME", "LASTNAME", "Last"]
FIRST_COLUMNS = ["First Name", "FIRST NAME", "FIRSTNAME", "First"]
EMAIL_COLUMNS = ["Email", "EMAIL", "E-mail", "Email Address"]

def Warn(*args):
    print("WARNING:", *args)

def FindColumn(fields, candidates, wanted=None):
    if wanted is not None:
        if wanted in fields: return wanted
        raise RuntimeError("Column '%s' not found in %s" % (wanted, fields))
    for c in candidates:
        if c in fields: return c
    return None

def NormalizeId(text):
    text = (text or "").strip()
    if text.endswith(".0"): text = text[:-2]
    return text

def NormalizeName(last, first):
    return ((last or "").strip().lower(), (first or "").strip().lower())

def NameFromEmail(email):
    local = (email or "").strip().split("@")[0]
    parts = [p for p in local.split(".") if p and not p.isdigit()]
    if len(parts) < 2: return None
    return NormalizeName(parts[-1], parts[0])

NOT_ASSIGNED = ["--"]

def ParseNumber(text):
    # Returns a float, or None if the cell holds no number.
    if text is None: return None
    text = text.strip().replace("%", "")
    if text in ("", "-", "nan", "NaN", "N/A", "n/a") or text in NOT_ASSIGNED:
        return None
    try: return float(text)
    except ValueError: return None

def NotAssigned(text):
    # Pearson writes "--" for an item that was not assigned to the
    # student; such an item is ignored rather than scored 0.
    return text is not None and text.strip() in NOT_ASSIGNED

###########################################################
# The roster: one entry per student with "SID", "LASTNAME", "FIRSTNAME"
# and the original row, so that the output can repeat its columns.
class Roster:
    def __init__(self, path, spec):
        self.fields = list()
        self.student = list()
        with io.open(path, "r", encoding="utf-8-sig", errors="ignore",
                     newline="") as f:
            reader = csv.DictReader(f)
            self.fields = [k for k in reader.fieldnames
                           if k is not None and k.strip() != ""]
            idCol = FindColumn(self.fields, ID_COLUMNS, spec.get("id_column"))
            lastCol = FindColumn(self.fields, LAST_COLUMNS,
                                 spec.get("last_name_column"))
            firstCol = FindColumn(self.fields, FIRST_COLUMNS,
                                  spec.get("first_name_column"))
            if idCol is None or lastCol is None or firstCol is None:
                raise RuntimeError("Roster needs id, last and first name"
                                   " columns, found %s" % self.fields)
            for row in reader:
                sid = NormalizeId(row[idCol])
                if sid == "": continue
                self.student.append({
                    "SID": sid,
                    "LASTNAME": row[lastCol].strip(),
                    "FIRSTNAME": row[firstCol].strip(),
                    "NAME": NormalizeName(row[lastCol], row[firstCol]),
                    "row": row})
        print("Students on roster", len(self.student))

    def AddAlias(self, who, name):
        student = self.Find(who)
        if student is None:
            raise RuntimeError("Alias for unknown student %r" % who)
        if "," not in str(name):
            raise RuntimeError("Alias %r must be written 'Last, First'" % name)
        student.setdefault("ALIASES", list()).append(
            NormalizeName(*str(name).split(",", 1)))

    def Find(self, who):
        # Find a student by id or by "Last, First" (case insensitive).
        who = str(who)
        for s in self.student:
            if s["SID"] == NormalizeId(who): return s
        if "," in who:
            name = NormalizeName(*who.split(",", 1))
            for s in self.student:
                if s["NAME"] == name: return s
        return None

###########################################################
# A CSV file with scores.  The header row is found automatically (the
# first row that holds an id, name or email column), so the extra
# lines that Pearson or the scanning centre put at the top are
# skipped.  The items are the columns holding the scores, each with
# its maximum.
class ScoreTable:
    def __init__(self, name, path, spec):
        self.name = name
        self.spec = spec
        with io.open(path, "r", encoding="utf-8-sig", errors="ignore",
                     newline="") as f:
            lines = [[c.strip() for c in row] for row in csv.reader(f)]
        header = spec.get("header_row")
        if header is None:
            for i, row in enumerate(lines):
                if any(c in row for c in ID_COLUMNS+LAST_COLUMNS+EMAIL_COLUMNS):
                    header = i + 1; break
            if header is None:
                raise RuntimeError("No header row found in " + path)
        self.fields = lines[header-1]
        data = lines[header + spec.get("skip_after_header", 0):]
        self.rows = [dict(zip(self.fields, r)) for r in data if any(r)]
        self.items = self.SelectItems(path)
        self.BuildIndex(path)
        print("%-12s %4d rows, %3d score column%s from %s"
              % (name, len(self.rows), len(self.items),
                 "" if len(self.items) == 1 else "s", os.path.basename(path)))

    def SelectItems(self, path):
        spec = self.spec
        if "column" in spec:
            patterns = [spec["column"]]
        elif "columns" in spec:
            patterns = spec["columns"]
            if isinstance(patterns, str): patterns = [patterns]
        else:
            raise RuntimeError("Category %s needs 'column' or 'columns'"
                               % self.name)
        columns = list()
        for p in patterns:
            matched = [f for f in self.fields if f and fnmatch.fnmatchcase(f, p)]
            if not matched:
                raise RuntimeError("No column matches '%s' in %s" % (p, path))
            columns += [m for m in matched if m not in columns]
        excluded = spec.get("exclude_columns") or list()
        if isinstance(excluded, str): excluded = [excluded]
        columns = [c for c in columns
                   if not any(fnmatch.fnmatchcase(c, e) for e in excluded)]
        if not columns:
            raise RuntimeError("No score columns left for %s" % self.name)
        # The maximum of each column: a number for all of them, a
        # mapping per column, or a row of the file (e.g. Pearson's
        # "Assigned Points:" row).  A column whose maximum is 0 or
        # missing is not an assigned item and is ignored.
        maximum = spec.get("max", 100)
        maxima = dict()
        if "max_row" in spec:
            label = str(spec["max_row"])
            rows = [r for r in self.rows if label in r.values()]
            if not rows:
                raise RuntimeError("No row labelled '%s' in %s" % (label, path))
            for c in columns: maxima[c] = ParseNumber(rows[0].get(c))
            self.rows = [r for r in self.rows if r is not rows[0]]
        elif isinstance(maximum, dict):
            for c in columns: maxima[c] = maximum.get(c)
        else:
            for c in columns: maxima[c] = float(maximum)
        items = [(c, maxima[c]) for c in columns if maxima[c]]
        if len(items) < len(columns):
            print("   %s: %d column%s with no points ignored" % (
                self.name, len(columns)-len(items),
                "" if len(columns)-len(items) == 1 else "s"))
        return items

    def BuildIndex(self, path):
        # Index the rows by every way of identifying a student that the
        # file supports; a student is looked up in the order given by
        # "match" (default: id, then name, then email).
        spec = self.spec
        idCol = FindColumn(self.fields, ID_COLUMNS, spec.get("id_column"))
        lastCol = FindColumn(self.fields, LAST_COLUMNS, spec.get("last_name_column"))
        firstCol = FindColumn(self.fields, FIRST_COLUMNS, spec.get("first_name_column"))
        emailCol = FindColumn(self.fields, EMAIL_COLUMNS, spec.get("email_column"))
        match = spec.get("match")
        if match is None:
            # Every way the file supports, id first.
            match = list()
            if idCol is not None: match.append("sid")
            if lastCol is not None and firstCol is not None: match.append("name")
            if emailCol is not None: match.append("email")
            if not match:
                raise RuntimeError("No id, name or email columns in %s" % path)
        if isinstance(match, str): match = [match]
        self.match = match
        self.index = {m: dict() for m in match}
        for m in match:
            if m == "sid" and idCol is None:
                raise RuntimeError("No id column in %s" % path)
            if m == "name" and (lastCol is None or firstCol is None):
                raise RuntimeError("No name columns in %s" % path)
            if m == "email" and emailCol is None:
                raise RuntimeError("No email column in %s" % path)
            if m not in ("sid", "name", "email"):
                raise RuntimeError("Unknown match mode '%s'" % m)
        self.unmatched = list()
        for row in self.rows:
            keys = dict()
            if "sid" in match: keys["sid"] = NormalizeId(row.get(idCol))
            if "name" in match:
                keys["name"] = NormalizeName(row.get(lastCol), row.get(firstCol))
            if "email" in match: keys["email"] = NameFromEmail(row.get(emailCol))
            row["_keys"] = keys
            row["_used"] = False
            for m, k in keys.items():
                if not k or k == ("", ""): continue
                if k in self.index[m]:
                    Warn("%s: duplicate entry for %s in %s, the first is used"
                         % (self.name, k, os.path.basename(path)))
                    continue
                self.index[m][k] = row

    def Lookup(self, student):
        for m in self.match:
            keys = [student["SID"]] if m == "sid" \
                else [student["NAME"]] + student.get("ALIASES", [])
            for key in keys:
                row = self.index[m].get(key)
                if row is not None:
                    row["_used"] = True
                    return row
        return None

    def UsedKeys(self):
        # The keys of the rows that were matched to a roster student.
        return {k for row in self.rows if row["_used"]
                for k in row["_keys"].values() if k and k != ("", "")}

    def Unused(self, usedKeys):
        # Rows of the file that belong to nobody on the roster: none of
        # their keys was matched, in this table or in another table
        # reading the same file for another section.
        out = list()
        for row in self.rows:
            keys = row["_keys"]
            if row["_used"] or any(k in usedKeys for k in keys.values()):
                continue
            label = keys.get("sid") or ""
            name = keys.get("name") or keys.get("email")
            if name and name != ("", ""):
                label = (label + " " + name[0].title() + " " + name[1].title()).strip()
            if label: out.append(label)
        return out

###########################################################
# Score one category for one student: the average of the item scores
# in percent after leaving out the items named in dropItems (glob
# patterns) and dropping the lowest ones.  Returns the score (None if
# the student is not in the file) and the list of items used, for the
# detailed breakdown.
def CategoryScore(table, student, dropLowest, missingItem, dropItems=(),
                  notAssigned="ignore"):
    row = table.Lookup(student)
    if row is None: return None, list()
    values = list()
    for column, maximum in table.items:
        if any(fnmatch.fnmatchcase(column, d) for d in dropItems):
            values.append((column, ParseNumber(row.get(column)), maximum, None))
            continue
        v = ParseNumber(row.get(column))
        if v is None:
            if missingItem == "ignore" or (
                    notAssigned == "ignore" and NotAssigned(row.get(column))):
                values.append((column, None, maximum, None)); continue
            v = 0.0
        values.append((column, v, maximum, 100.0*v/maximum))
    scored = [v for v in values if v[3] is not None]
    scored.sort(key=lambda v: v[3])
    dropped = scored[:dropLowest] if dropLowest > 0 else list()
    kept = scored[len(dropped):]
    score = sum(v[3] for v in kept)/len(kept) if kept else 0.0
    detail = [(c, v, m, p, (c, v, m, p) in dropped or p is None and v is not None)
              for c, v, m, p in values]
    return score, detail

###########################################################
# The main code begins here.

configFile = options.config[0]
config = LoadYaml(configFile)
if not isinstance(config, dict) or "categories" not in config:
    raise RuntimeError("The configuration needs at least 'roster' and"
                       " 'categories'")
baseDir = os.path.dirname(os.path.abspath(configFile))
def Path(p):
    return p if os.path.isabs(p) else os.path.join(baseDir, p)

roster = Roster(Path(config["roster"]), config.get("roster_columns", {}))
NOT_ASSIGNED = [str(v) for v in config.get("not_assigned", NOT_ASSIGNED)]

# Other names under which a student appears in some files.
for a in config.get("aliases", None) or list():
    names = a.get("names") or [a.get("name")]
    for name in names: roster.AddAlias(a.get("student", ""), name)

# The categories, in the order of the configuration.  A category may
# have "sections": overrides of its settings for the students of a
# section of the roster (another file, another number of drops, ...).
sectionColumn = config.get("section_column", "Section")
categories = list()
tables = dict()
for name, spec in config["categories"].items():
    if spec is None:
        raise RuntimeError("Category %s needs a 'file'" % name)
    spec.setdefault("weight", 0)
    spec.setdefault("title", name)
    spec.setdefault("extra_credit", False)
    spec.setdefault("drop_lowest", 0)
    spec.setdefault("missing_item", "zero")
    spec.setdefault("missing_student", "zero")
    spec.setdefault("not_assigned", "ignore")
    categories.append(name)
    specs = {None: spec}
    for section, override in (spec.get("sections") or {}).items():
        merged = {k: v for k, v in spec.items() if k != "sections"}
        override = override or {}
        # A section that names its own columns or maxima replaces the
        # category's, it does not add to them.
        for group in (("column", "columns"), ("max", "max_row")):
            if any(k in override for k in group):
                for k in group: merged.pop(k, None)
        merged.update(override)
        specs[str(section).strip()] = merged
    tables[name] = dict()
    for section, sp in specs.items():
        if "file" not in sp:
            raise RuntimeError("Category %s needs a 'file'" % name)
        label = name if section is None else "%s [%s]" % (name, section)
        tables[name][section] = (sp, ScoreTable(label, Path(sp["file"]), sp))
    if len(specs) > 1 and sectionColumn not in roster.fields:
        raise RuntimeError("Category %s has sections but the roster has no"
                           " '%s' column" % (name, sectionColumn))

def SpecFor(name, student):
    # The settings and the score table of a category for one student.
    section = str(student["row"].get(sectionColumn, "")).strip()
    if section.endswith(".0"): section = section[:-2]
    return tables[name].get(section) or tables[name][None]
weights = {c: float(config["categories"][c]["weight"]) for c in categories}
regular = [c for c in categories if not config["categories"][c]["extra_credit"]]
bonus = [c for c in categories if config["categories"][c]["extra_credit"]]
print("Weights: %s = %g%%, extra credit: %s = %g%%" % (
    ", ".join("%s %g" % (c, weights[c]) for c in regular),
    sum(weights[c] for c in regular),
    ", ".join("%s %g" % (c, weights[c]) for c in bonus) or "none",
    sum(weights[c] for c in bonus)))

# The exceptions, keyed by student id.
exceptions = dict()
for e in config.get("exceptions", None) or list():
    student = roster.Find(e.get("student", ""))
    if student is None:
        raise RuntimeError("Exception for unknown student %r" % e.get("student"))
    for key in e:
        if key not in ("student", "note", "exclude", "redistribute",
                       "drop_lowest", "drop", "set", "letter"):
            raise RuntimeError("Unknown key '%s' in the exception for %s"
                               % (key, e["student"]))
    for c in (e.get("exclude") or []) + list((e.get("drop_lowest") or {})) \
            + list((e.get("set") or {})) + (e.get("redistribute") or []) \
            + list((e.get("drop") or {})):
        if c not in categories:
            raise RuntimeError("Unknown category '%s' in the exception for %s"
                               % (c, e["student"]))
    for c, items in (e.get("drop") or {}).items():
        if isinstance(items, str): items = [items]
        e["drop"][c] = [str(i) for i in items]
        columns = [column for sp, t in tables[c].values()
                   for column, maximum in t.items]
        for item in e["drop"][c]:
            if not any(fnmatch.fnmatchcase(column, item) for column in columns):
                raise RuntimeError("No item '%s' in %s for the exception for %s"
                                   % (item, c, e["student"]))
    exceptions.setdefault(student["SID"], list()).append(e)

# The letter grades: lower bound of the total for each letter.
letterGrades = config.get("letter_grades") or dict()
letters = sorted(letterGrades.items(), key=lambda kv: -float(kv[1]))
roundDigits = config.get("round_digits", None)

def RoundHalfUp(x, digits):
    # Like a spreadsheet's ROUND: 84.5 becomes 85 (Python's round gives 84).
    scale = 10.0**int(digits)
    return math.floor(x*scale + 0.5)/scale

def LetterGrade(total):
    if roundDigits is not None: total = RoundHalfUp(total, roundDigits)
    for letter, bound in letters:
        if total >= float(bound): return letter
    return letters[-1][0] if letters else ""

# Grade every student.
results = list()
for student in roster.student:
    sid = student["SID"]
    excl = exceptions.get(sid, list())
    scores, details, notes = dict(), dict(), list()
    dropLowest = {c: int(SpecFor(c, student)[0]["drop_lowest"]) for c in categories}
    dropItems = {c: list() for c in categories}
    forcedLetter = None
    excluded, redistribute = list(), None
    for e in excl:
        if e.get("note"): notes.append(e["note"])
        for c, n in (e.get("drop_lowest") or {}).items(): dropLowest[c] = int(n)
        for c, items in (e.get("drop") or {}).items(): dropItems[c] += items
        excluded += e.get("exclude") or []
        if e.get("redistribute"): redistribute = e["redistribute"]
        if e.get("letter"): forcedLetter = str(e["letter"])
    for c in categories:
        spec, table = SpecFor(c, student)
        score, detail = CategoryScore(table, student, dropLowest[c],
                                      spec["missing_item"], dropItems[c],
                                      spec["not_assigned"])
        if score is None:
            if spec["missing_student"] == "ignore":
                notes.append("not in %s" % c)
                if c not in excluded: excluded.append(c)
            score = 0.0
        scores[c] = score
        details[c] = detail
    for e in excl:
        for c, v in (e.get("set") or {}).items(): scores[c] = float(v)
    # The weights of this student: the weight of an excluded category
    # goes to the other categories, in proportion to their weights, or
    # to the categories named by "redistribute".
    w = dict(weights)
    moved = sum(w[c] for c in excluded)
    for c in excluded: w[c] = 0.0
    if moved > 0:
        targets = redistribute or [c for c in regular if c not in excluded]
        base = sum(w[c] for c in targets)
        if base <= 0:
            raise RuntimeError("Nothing left to carry the weight for %s %s"
                               % (student["LASTNAME"], student["FIRSTNAME"]))
        for c in targets: w[c] += moved*w[c]/base
    total = sum(w[c]*scores[c]/100.0 for c in categories)
    totalNoBonus = sum(w[c]*scores[c]/100.0 for c in regular)
    letter = forcedLetter or LetterGrade(total)
    results.append({"student": student, "scores": scores, "weights": w,
                    "details": details, "total": total,
                    "totalNoBonus": totalNoBonus, "letter": letter,
                    "notes": notes, "excluded": excluded,
                    "forced": forcedLetter is not None})

# Report what did not match.
for c in categories:
    missing = [r["student"] for r in results
               if SpecFor(c, r["student"])[1].Lookup(r["student"]) is None]
    if missing:
        print("%s: %d roster student%s not in the file (scored 0 unless"
              " missing_student is 'ignore'):" % (
                  c, len(missing), "" if len(missing) == 1 else "s"))
        for s in missing:
            print("    ", s["SID"], s["LASTNAME"], s["FIRSTNAME"])
    usedKeys = set()
    for sp, table in tables[c].values(): usedKeys |= table.UsedKeys()
    seen = set()
    for section, (sp, table) in tables[c].items():
        unused = [u for u in table.Unused(usedKeys) if u not in seen]
        seen |= set(unused)
        if unused:
            print("%s: %d row%s of %s match nobody on the roster:" % (
                c, len(unused), "" if len(unused) == 1 else "s",
                os.path.basename(sp["file"])))
            for u in unused: print("    ", u)

# The groups of students: everybody, then every section of the roster.
def Section(student):
    section = str(student["row"].get(sectionColumn, "")).strip()
    if section.endswith(".0"): section = section[:-2]
    return section
def SectionLabel(section):
    return "Section %02d" % int(section) if section.isdigit() else \
           "Section " + section
sections = sorted({Section(r["student"]) for r in results},
                  key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else s))
groups = [("All students", results)]
if len(sections) > 1:
    for s in sections:
        groups.append((SectionLabel(s),
                       [r for r in results if Section(r["student"]) == s]))

def Mean(values):
    return sum(values)/len(values) if values else 0.0

# Summary.
print("SUMMARY")
print("   %-12s %s" % ("", "".join("%18s" % label for label, g in groups)))
print("   %-12s %s" % ("students", "".join("%18d" % len(g) for label, g in groups)))
for c in categories:
    print("   %-12s %s" % (c, "".join(
        "%17.2f%%" % Mean([r["scores"][c] for r in g]) for label, g in groups)))
print("   %-12s %s" % ("total", "".join(
    "%18.2f" % Mean([r["total"] for r in g]) for label, g in groups)))
print("   %-12s %s" % ("w/o extra", "".join(
    "%18.2f" % Mean([r["totalNoBonus"] for r in g]) for label, g in groups)))
if letters:
    for label, g in groups:
        counts = dict()
        for r in g: counts[r["letter"]] = counts.get(r["letter"], 0) + 1
        print("   letter grades%s:" % (
            "" if label == groups[0][0] else " " + label.lower()),
            "  ".join("%s %d" % (l, counts[l]) for l, b in letters if l in counts),
            "".join("  %s %d" % (l, counts[l]) for l in counts
                    if l not in dict(letters)))
if exceptions:
    print("   %d student%s with exceptions" % (
        len(exceptions), "" if len(exceptions) == 1 else "s"))

# The students that a small bump would move to a higher letter.
nearBound = float(config.get("near_bound", 0.5))
if letters and nearBound > 0:
    scale = 10.0**int(roundDigits) if roundDigits is not None else None
    near = list()
    for r in results:
        if r["forced"]: continue
        higher = LetterGrade(r["total"] + nearBound)
        if higher == r["letter"]: continue
        threshold = float(letterGrades[higher])
        if scale: threshold -= 0.5/scale
        near.append((higher, threshold - r["total"], r))
    print("STUDENTS WITHIN %g OF A HIGHER LETTER: %d" % (nearBound, len(near)))
    for higher, needed, r in sorted(near, key=lambda x: -x[2]["total"]):
        s = r["student"]
        print("   %-28s %-10s total %6.2f  %-2s -> %-2s needs +%.2f" % (
            "%s %s" % (s["LASTNAME"], s["FIRSTNAME"]), s["SID"], r["total"],
            r["letter"], higher, max(needed, 0.0)))

# Detailed breakdown for the requested students.
for who in options.students:
    student = roster.Find(who)
    if student is None:
        Warn("No student", who); continue
    r = [r for r in results if r["student"] is student][0]
    print("=" * 70)
    print("%s %s  id %s" % (student["LASTNAME"], student["FIRSTNAME"], student["SID"]))
    for note in r["notes"]: print("   note:", note)
    for c in categories:
        print("   %-12s score %6.2f%%  weight %5.2f%%  contributes %6.2f%s" % (
            c, r["scores"][c], r["weights"][c],
            r["weights"][c]*r["scores"][c]/100.0,
            "  (excluded)" if c in r["excluded"] else ""))
        for column, v, m, p, dropped in r["details"][c]:
            if v is None: print("      %-40s   --" % column)
            elif p is None: print("      %-40s %7.2f / %-5g   dropped"
                                  % (column, v, m))
            else: print("      %-40s %7.2f / %-5g = %6.2f%%%s" % (
                column, v, m, p, "  dropped" if dropped else ""))
    print("   total %.2f (without extra credit %.2f)  letter %s"
          % (r["total"], r["totalNoBonus"], r["letter"]))

if options.dryRun:
    print("Dry run: no files written")
    sys.exit(0)

# The results file: the roster columns, the score of every category,
# the weight used for it, the totals and the letter.
output = config.get("output")
if output:
    fields = list(roster.fields)
    for c in categories: fields.append(c)
    for c in categories: fields.append("weight " + c)
    fields += ["Total", "Total w/o extra credit", "Letter", "Notes"]
    with open(Path(output), "w", newline="") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = dict(r["student"]["row"])
            for c in categories:
                row[c] = "%.2f" % r["scores"][c]
                row["weight " + c] = "%g" % r["weights"][c]
            row["Total"] = "%.2f" % r["total"]
            row["Total w/o extra credit"] = "%.2f" % r["totalNoBonus"]
            row["Letter"] = r["letter"]
            row["Notes"] = "; ".join(r["notes"])
            writer.writerow(row)
    print("Results written to", Path(output))

# Histograms of the totals and of every category: one figure each,
# with a panel for all the students and one per section.
plots = config.get("plots")
if plots:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed: no plots")
        plots = None
if plots:
    surface, ink, muted, blue = "#fcfcfb", "#0b0b0b", "#52514e", "#2a78d6"
    grid = "#e3e2de"
    series = [blue, "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]

    def Frame(ax):
        ax.set_facecolor(surface)
        ax.yaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        for side in ax.spines.values(): side.set_color(muted)
        ax.tick_params(colors=muted, length=3)

    def LetterLines(ax, bounds, top):
        for letter, bound in bounds:
            if 0 < bound <= top:
                ax.axvline(bound, color=muted, linewidth=0.6, zorder=1)
                ax.text(bound, ax.get_ylim()[1]*0.98, " " + letter,
                        color=muted, fontsize=7, va="top")

    def Histogram(panels, title, xlabel, path, bounds=()):
        # panels: [(label, values)].  Scores of 0 are left out.
        panels = [(label, [v for v in values if v > 0]) for label, values in panels]
        top = max([100] + [v for label, values in panels for v in values])
        top = 5*int(-(-top//5))             # the last bin includes its right edge
        bins = range(0, top + 1, 5)
        fig, axes = plt.subplots(len(panels), 1, sharex=True, dpi=150,
                                 figsize=(8, 1.2 + 2.2*len(panels)))
        if len(panels) == 1: axes = [axes]
        fig.patch.set_facecolor(surface)
        for ax, (label, values) in zip(axes, panels):
            Frame(ax)
            ax.hist(values, bins=bins, color=blue, rwidth=0.9, zorder=2)
            mean = Mean(values)
            ax.axvline(mean, color=ink, linestyle="--", linewidth=1.5, zorder=3,
                       label="%s: n = %d, mean = %.1f" % (label, len(values), mean))
            LetterLines(ax, bounds, top)
            ax.set_ylabel("Number of students", color=ink)
            ax.legend(frameon=False, loc="upper left", labelcolor=ink)
        axes[0].set_title(title, color=ink, loc="left")
        axes[-1].set_xlabel(xlabel, color=ink)
        fig.tight_layout(); fig.savefig(path, facecolor=surface); plt.close(fig)

    def Cumulative(panels, title, xlabel, path, bounds=()):
        # The fraction of the students with at least a given total, one
        # curve per group.  Scores of 0 are left out.
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        fig.patch.set_facecolor(surface); Frame(ax)
        top = 100
        for i, (label, values) in enumerate(panels):
            values = sorted(v for v in values if v > 0)
            if not values: continue
            top = max(top, values[-1])
            n = len(values)
            x = [0] + values + [values[-1]]
            y = [100.0] + [100.0*(n - k)/n for k in range(n)] + [0.0]
            ax.plot(x, y, drawstyle="steps-post", linewidth=2, zorder=3,
                    color=ink if i == 0 else series[(i - 1) % len(series)],
                    label="%s (n = %d)" % (label, n))
        top = 5*int(-(-top//5))
        ax.set_xlim(0, top); ax.set_ylim(0, 100)
        LetterLines(ax, bounds, top)
        ax.set_xlabel(xlabel, color=ink)
        ax.set_ylabel("Students with at least this total (%)", color=ink)
        ax.set_title(title, color=ink, loc="left")
        ax.legend(frameon=False, loc="lower left", labelcolor=ink)
        fig.tight_layout(); fig.savefig(path, facecolor=surface); plt.close(fig)

    def ShortLabels(names):
        # Strip what all the item names share, e.g. "Lecture 05 Homework"
        # becomes "05"; returns the labels and the stripped text.
        if len(names) < 2: return list(names), ""
        prefix = os.path.commonprefix(names)
        suffix = os.path.commonprefix([n[::-1] for n in names])[::-1]
        if len(prefix) + len(suffix) >= min(len(n) for n in names):
            suffix = ""
        short = [n[len(prefix):len(n) - len(suffix)] or n for n in names]
        return short, (prefix + "…" + suffix).strip() if prefix or suffix else ""

    def ItemMeans(c, path):
        # The mean score of every item of a category: one panel per group
        # when the sections share the file, else one per section.
        if list(tables[c]) == [None]:
            panels = [(label, tables[c][None][1], g) for label, g in groups]
        else:
            panels = [(SectionLabel(s), SpecFor(c, g[0]["student"])[1], g)
                      for s, (label, g) in zip(sections, groups[1:]) if g]
        panels = [p for p in panels if len(p[1].items) > 1]
        if not panels: return
        fig, axes = plt.subplots(len(panels), 1, dpi=150,
                                 figsize=(8, 1.6 + 2.4*len(panels)))
        if len(panels) == 1: axes = [axes]
        fig.patch.set_facecolor(surface)
        for ax, (label, table, g) in zip(axes, panels):
            Frame(ax)
            names = [column for column, m in table.items]
            means, counts = list(), list()
            for column in names:
                pcts = [100.0*v/m for r in g for col, v, m, p, d in r["details"][c]
                        if col == column and v is not None and m]
                means.append(Mean(pcts)); counts.append(len(pcts))
            short, stripped = ShortLabels(names)
            ax.bar(range(len(names)), means, color=blue, width=0.8, zorder=2)
            ax.axhline(Mean(means), color=ink, linestyle="--", linewidth=1.5,
                       zorder=3)
            ax.set_title("%s: %d students, mean of the items = %.1f (dashed)"
                         % (label, len(g), Mean(means)), color=muted,
                         fontsize=9, loc="left")
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(short, fontsize=7, color=muted,
                               rotation=90 if max(len(s) for s in short) > 3
                               or len(short) > 20 else 0)
            ax.set_ylim(0, 100); ax.set_ylabel("Mean score (%)", color=ink)
            ax.set_xlabel(stripped, color=muted, fontsize=8)
        fig.suptitle("Items of %s" % config["categories"][c]["title"],
                     color=ink, x=0.02, ha="left")
        fig.tight_layout(); fig.savefig(path, facecolor=surface); plt.close(fig)

    def Scatter(cx, cy, path):
        # One category against another, a point per student, the sections
        # told apart by colour.  Students with a 0 in either are left out.
        fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
        fig.patch.set_facecolor(surface); Frame(ax)
        ax.xaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
        ax.plot([0, 100], [0, 100], color=muted, linewidth=0.6,
                linestyle="--", zorder=1)
        for i, (label, g) in enumerate(groups[1:] or groups):
            xs = [r["scores"][cx] for r in g if r["scores"][cx] > 0 and r["scores"][cy] > 0]
            ys = [r["scores"][cy] for r in g if r["scores"][cx] > 0 and r["scores"][cy] > 0]
            ax.scatter(xs, ys, s=22, color=series[i % len(series)], zorder=3,
                       edgecolors=surface, linewidths=0.6, alpha=0.9,
                       label="%s (n = %d)" % (label, len(xs)))
        titles = config["categories"]
        ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.set_aspect("equal")
        ax.set_xlabel("%s (%%)" % titles[cx]["title"], color=ink)
        ax.set_ylabel("%s (%%)" % titles[cy]["title"], color=ink)
        ax.set_title("%s against %s" % (titles[cy]["title"], titles[cx]["title"]),
                     color=ink, loc="left")
        ax.legend(frameon=False, loc="upper left", labelcolor=ink)
        fig.tight_layout(); fig.savefig(path, facecolor=surface); plt.close(fig)

    folder = Path(plots)
    os.makedirs(folder, exist_ok=True)
    Histogram([(label, [r["total"] for r in g]) for label, g in groups],
              "Distribution of the totals", "Total",
              os.path.join(folder, "total.png"),
              [(l, float(b)) for l, b in letters])
    Cumulative([(label, [r["total"] for r in g]) for label, g in groups],
               "Students above each total", "Total",
               os.path.join(folder, "total-cumulative.png"),
               [(l, float(b)) for l, b in letters])
    if config.get("plot_categories", True):
        for c in categories:
            Histogram([(label, [r["scores"][c] for r in g]) for label, g in groups],
                      "Distribution of %s" % config["categories"][c]["title"],
                      "Score (%)", os.path.join(folder, c + ".png"))
            if any(table.items and len(table.items) > 1
                   for sp, table in tables[c].values()):
                ItemMeans(c, os.path.join(folder, c + "-items.png"))
    for pair in config.get("scatter") or []:
        if not isinstance(pair, list) or len(pair) != 2 or \
                any(c not in categories for c in pair):
            raise RuntimeError("scatter needs pairs of categories, not %r" % (pair,))
        Scatter(pair[0], pair[1], os.path.join(folder, "scatter-%s-%s.png" % tuple(pair)))
    print("Plots written to", folder)
