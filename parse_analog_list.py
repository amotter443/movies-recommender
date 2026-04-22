"""
parse_analog_list.py -- convert analog_list.txt -> analog_watchlist.csv

Usage:
    python parse_analog_list.py                          # uses default paths
    python parse_analog_list.py my_list.txt out.csv      # custom paths

Input format (analog_list.txt):
    Free-text movie list with sections like:
        Kanopy: Title One, Title Two Director, Title Three Actor
        Criterion: Title, RW Title Two, ...
        RW Title, Title Two
        Title HBO Max
        Title library
        Leaving Criterion: Title one, Title two

Output: analog_watchlist.csv with columns: Name, Year, Notes
"""

import csv
import re
import sys
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
_HERE = Path(__file__).parent
DEFAULT_INPUT  = _HERE / "data" / "analog_list.txt"
DEFAULT_OUTPUT = _HERE / "data" / "analog_watchlist.csv"

# -- Service / prefix maps -----------------------------------------------------
SERVICE_PREFIXES: dict[str, str] = {
    "leaving criterion": "Leaving Criterion Channel",
    "criterion":         "Criterion Channel",
    "kanopy":            "Kanopy",
    "library":           "Library",
    "vod":               "VOD",
    "internet archive":  "Internet Archive",
    "prime":             "Prime",
    "hbo max":           "Max",
    "max":               "Max",
    "hulu":              "Hulu",
}

INLINE_SERVICE_RE = re.compile(
    r"\s+(hbo\s+max|max|hulu|prime|library|kanopy|criterion)\s*$",
    flags=re.IGNORECASE,
)
INLINE_SERVICE_MAP: dict[str, str] = {
    "hbo max":   "Max",
    "max":       "Max",
    "hulu":      "Hulu",
    "prime":     "Prime",
    "library":   "Library",
    "kanopy":    "Kanopy",
    "criterion": "Criterion Channel",
}

# -- Annotation stripping ------------------------------------------------------

# Leading director/author names that prefix a title token
# ("Win Wenders Notebook on Cities and Clothes" -> "Notebook on Cities and Clothes")
LEADING_ANNOTATION_RE = re.compile(
    r"^(almodovar|godard|truffaut|bresson|haneke|malick|kubrick|"
    r"kurosawa|herzog|tarkovsky|bergman|fellini|rivette|"
    r"win\s+wenders|joachim\s+trier)\s+",
    flags=re.IGNORECASE,
)

# Trailing annotations: most specific (multi-word) must come before single-word.
# The regex matches WHITESPACE + ANNOTATION + everything to end-of-string.
_TRAILING_PARTS = [
    # Multi-word names (order: longest/most specific first)
    r"win\s+wenders",
    r"michael\s+haneke",
    r"steve\s+mcqueen",
    r"river\s+phoenix",
    r"orson\s+(welles?|wells?)",  # matches Wells, Welles, Welle
    r"buster\s+keaton",
    r"cate\s+blanchett(\s+rec)?",
    r"juliette\s+binoche",
    r"laurence\s+olivier",
    r"bette\s+dav[ie][sd]?",     # Davis / David (typo)
    r"anna\s+may\s+wong",
    r"isabelle\s+adji[ai]ni?",   # Adjani / Adjiani (both spellings)
    r"isabelle\s+huppert",
    r"hepburn\s+rogers",
    r"joachim\s+trier",
    r"lina\s+brocka",
    r"agnes\s+varda",
    r"celinne?\s+sciamma",
    # Edition / rec notes
    r"director\s*['\u2019]?s?\s+cut",
    r"first\s+best\s+picture",
    # "by Author" and "aka Other Title"
    r"by\s+\w+(\s+\w+)?",
    r"aka\s+.+",
    # Single-word director/author surnames (after multi-word handled above)
    r"bresson|godard|pialat|truffaut|hitchcock|malick|cassavetes|"
    r"herzog|kurosawa|obayashi|sciamma|haneke|brocka|almodovar|"
    r"tarkovsky|bergman|varda|didion|fellini|wenders",
    # Inline service tags that can appear on individual tokens
    r"criterion|kanopy|library|prime",
]

TRAILING_ANNOTATION_RE = re.compile(
    r"\s+\b(" + "|".join(_TRAILING_PARTS) + r")\b.*$",
    flags=re.IGNORECASE,
)

# Unicode -> ASCII normalization map for common typographic characters
_UNICODE_NORM = str.maketrans({
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote / apostrophe
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2013": "-",   # en dash
    "\u2014": "--",  # em dash
})

# Known title corrections applied after stripping (lowercased key -> correct value)
TITLE_CORRECTIONS: dict[str, str] = {
    "alice doesn't livr here anymore":            "Alice Doesn't Live Here Anymore",
    "nickelboys":                                 "Nickel Boys",
    "ratchcatcher":                               "Ratcatcher",
    "peewee's big adventure":                     "Pee-wee's Big Adventure",
    "a nos amours":                               "A Nos Amours",
    "mommy dearest":                              "Mommie Dearest",
    "totoro":                                     "My Neighbor Totoro",
    "butch cassidy":                              "Butch Cassidy and the Sundance Kid",
    "7 chances":                                  "Seven Chances",
    "reprise":                                    "Reprise",
    "masculin feminin":                           "Masculin Feminin",
    "water lilies celinne":                       "Water Lilies",  # fallback
}

# -- Title case ----------------------------------------------------------------
_LOWERCASE_WORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet",
    "at", "by", "for", "in", "of", "on", "to", "up", "as", "vs", "vs.",
    "with", "into", "onto", "upon",
    "de", "du", "la", "le", "les", "et", "von", "van", "di", "par",
}


def _title_case(s: str) -> str:
    """Smart title-case. First/last word always capitalized."""
    words = s.split()
    result = []
    for i, w in enumerate(words):
        if not w:
            continue
        # Preserve non-ASCII mixed-case words (e.g. "À", "Féminin")
        if not w.isascii() and not w.islower():
            result.append(w)
        elif i == 0 or i == len(words) - 1:
            # capitalize() lowercases the rest, which is what we want for ALL-CAPS
            result.append(w.capitalize())
        elif w.lower() in _LOWERCASE_WORDS:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    return " ".join(result)


def _clean_title(raw: str) -> str:
    """
    Strip annotations, normalize caps, apply known corrections.
    Cleaning pipeline:
      1. Normalize Unicode punctuation to ASCII
      2. Strip leading RW marker
      3. Strip leading director/author prefix
      4. Strip trailing annotations (up to 3 passes)
      5. Normalize whitespace; strip trailing commas/colons (not periods)
      6. Look up in corrections dict
      7. Apply title case
    """
    t = raw.strip()
    if not t:
        return ""

    # 1. Normalize Unicode punctuation
    t = t.translate(_UNICODE_NORM)

    # 2. Strip leading RW marker
    t = re.sub(r"^rw\s+", "", t, flags=re.IGNORECASE).strip()

    # 3. Strip leading director prefix
    t = LEADING_ANNOTATION_RE.sub("", t).strip()

    # 4. Strip trailing annotations (iterative until stable)
    for _ in range(4):
        cleaned = TRAILING_ANNOTATION_RE.sub("", t).strip().rstrip(",:").strip()
        if cleaned == t:
            break
        t = cleaned

    # 5. Normalize whitespace
    t = re.sub(r"\s{2,}", " ", t).strip()

    if not t:
        return ""

    # 6. Corrections dict (lowercased, also with normalized apostrophe)
    key = t.lower()
    if key in TITLE_CORRECTIONS:
        return TITLE_CORRECTIONS[key]

    # 7. Title case (applied unconditionally to fix mixed input casing)
    return _title_case(t)


# -- Line parsing --------------------------------------------------------------
def _strip_line_prefix(line: str) -> str:
    """Remove leading line-number + arrow artifacts from text editors."""
    return re.sub(r"^\s*\d+[\u2192>]\s*", "", line).strip()


def _detect_service_prefix(line: str) -> tuple[str | None, str]:
    """Return (canonical_service, remainder) if line starts with 'Service:'."""
    for key in sorted(SERVICE_PREFIXES, key=len, reverse=True):
        if line.lower().startswith(key + ":"):
            return SERVICE_PREFIXES[key], line[len(key) + 1:].strip()
    return None, line


def _merge_comma_split_titles(tokens: list[str]) -> list[str]:
    """
    Re-join tokens split on a comma that is actually inside a title
    (e.g. "This Is Not a Burial, It's a Resurrection").
    Only merges when the next token begins with "It's" or "or the/a/an".
    """
    continuation_re = re.compile(
        r"^(it'?s?\b|or\s+(the|a|an)\b)",
        flags=re.IGNORECASE,
    )
    merged: list[str] = []
    for tok in tokens:
        tok_s = tok.strip()
        if not tok_s:
            continue
        if merged and continuation_re.match(tok_s):
            merged[-1] = merged[-1].rstrip() + ", " + tok_s
        else:
            merged.append(tok)
    return merged


def _parse_line(line: str) -> list[dict]:
    """Parse one logical line into a list of {name, year, notes} dicts."""
    line = line.strip()
    if not line or line.lower() in ("watching", ""):
        return []

    entries: list[dict] = []

    # ── Service-prefix block ("Criterion: title, title, ...") ────────────────
    service, remainder = _detect_service_prefix(line)
    if service:
        tokens = _merge_comma_split_titles(remainder.split(","))
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            is_rw = bool(re.match(r"^rw\s+", tok, re.IGNORECASE))
            name = _clean_title(tok)
            if not name:
                continue
            notes = f"{service}; Rewatch" if is_rw else service
            entries.append({"name": name, "year": "", "notes": notes})
        return entries

    # ── Standalone RW prefix ("RW Juno, Jackie Brown") ───────────────────────
    rw_match = re.match(r"^rw[:\s]+(.+)", line, re.IGNORECASE)
    if rw_match:
        tokens = _merge_comma_split_titles(rw_match.group(1).split(","))
        for tok in tokens:
            name = _clean_title(tok)
            if name:
                entries.append({"name": name, "year": "", "notes": "Rewatch"})
        return entries

    # ── Single entry with trailing inline service tag ─────────────────────────
    inline_match = INLINE_SERVICE_RE.search(line)
    if inline_match:
        svc_raw = inline_match.group(1).lower()
        notes = INLINE_SERVICE_MAP.get(svc_raw, svc_raw.title())
        name = _clean_title(line[: inline_match.start()])
        if name:
            entries.append({"name": name, "year": "", "notes": notes})
        return entries

    # ── Fallback: whole line is a single title ────────────────────────────────
    name = _clean_title(line)
    if name:
        entries.append({"name": name, "year": "", "notes": ""})
    return entries


# -- Main conversion -----------------------------------------------------------
def parse_analog_list(input_path: Path, output_path: Path) -> list[dict]:
    raw = input_path.read_text(encoding="utf-8")

    all_entries: list[dict] = []
    seen_names: set[str] = set()

    for line in raw.splitlines():
        line = _strip_line_prefix(line)
        for entry in _parse_line(line):
            key = entry["name"].lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                all_entries.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Name", "Year", "Notes"])
        writer.writeheader()
        for e in all_entries:
            writer.writerow({"Name": e["name"], "Year": e["year"], "Notes": e["notes"]})

    return all_entries


# -- CLI -----------------------------------------------------------------------
if __name__ == "__main__":
    input_path  = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    entries = parse_analog_list(input_path, output_path)

    print(f"Parsed {len(entries)} entries -> {output_path}\n")
    for e in entries:
        svc = f"  [{e['notes']}]" if e["notes"] else ""
        # Encode for Windows console without crashing on non-ASCII
        line = f"  {e['name']}{svc}"
        print(line.encode("ascii", errors="replace").decode("ascii"))
