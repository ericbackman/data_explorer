"""Classify free-text absence reasons into a fixed taxonomy.

Three sources feed the injury index and each writes reasons in its own words:

- NBA box-score comments, 1996-97 on: ``DND - Sprained Left Ankle``,
  ``DNP - Injury/Illness``, ``NWT - Personal Reasons``.
- The NBA's official injury reports, 2018-12 on: ``Injury/Illness - Left Ankle;
  Sprain``, ``Rest``, ``G League - Two-Way``.
- Pro Sports Transactions injured-list notes (via open mirrors):
  ``sprained left ankle (DNP)``, ``placed on IL for personal reasons``.

``classify(text)`` maps any of them to one ``Label``. The rules are keyword
tables, applied in a fixed order, so the same text always gets the same label
and a reviewer can read why. Unknown text is labelled ``unknown`` rather than
guessed; the share of unknowns per season is a published number, not a
hidden one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- categories
# Why the player was absent. Only `injury` rows feed the body-location charts.
INJURY = "injury"
ILLNESS = "illness"
REST = "rest"
COACH = "coach"  # coach's decision (healthy scratch)
SUSPENSION = "suspension"
PERSONAL = "personal"
PROTOCOL = "protocol"  # health and safety protocols (COVID era)
ROSTER = "roster"  # trade pending, G League, two-way, not with team, inactive
INJURY_UNSPECIFIED = "injury_unspecified"  # "Injury/Illness" with no body part
UNKNOWN = "unknown"

CATEGORIES = (
    INJURY,
    INJURY_UNSPECIFIED,
    ILLNESS,
    REST,
    COACH,
    SUSPENSION,
    PERSONAL,
    PROTOCOL,
    ROSTER,
    UNKNOWN,
)

# ---------------------------------------------------------------- locations
# Body location for `injury` rows, and the coarser region used for the
# below-the-knee question. Order matters: the first matching location wins,
# so the more specific words (achilles before calf, hamstring before leg)
# come first.
LOCATION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # location, region, keywords (matched as whole words, case-insensitive)
    ("achilles", "below_knee", ("achilles", "achillies", "achiles")),
    ("ankle", "below_knee", ("ankle", "ankles", "talus", "syndesmosis", "syndesmotic", "tib/fib", "tib-fib")),
    (
        "foot",
        "below_knee",
        (
            "foot",
            "feet",
            "toe",
            "toes",
            "heel",
            "plantar",
            "metatarsal",
            "lisfranc",
            "midfoot",
            "mid-foot",
            "forefoot",
            "sesamoid",
            "navicular",
            "cuboid",
            "arch",
            "bunion",
            "turf toe",
            "cuneiform",
            "mtp",
            "retrocalcaneal",
            "posterior tibialis",
            "posterior tibial",
            "calcaneus",
            "calcaneal",
            "phalanx",
        ),
    ),
    (
        "lower_leg",
        "below_knee",
        ("calf", "calves", "shin", "shins", "tibia", "tibial", "fibula", "fibular", "soleus", "gastrocnemius", "lower leg", "peroneal"),
    ),
    (
        "knee",
        "knee",
        (
            "knee",
            "knees",
            "acl",
            "mcl",
            "pcl",
            "lcl",
            "meniscus",
            "meniscal",
            "patella",
            "patellar",
            "patellofemoral",
            "kneecap",
            "quadriceps tendon",
            "quad tendon",
            "jumper's knee",
            "anterior cruciate",
            "medial collateral",
            "posterior cruciate",
            "lateral collateral",
            "patellar tendon",
        ),
    ),
    ("hamstring", "upper_leg", ("hamstring", "hamstrings")),
    (
        "quad_thigh",
        "upper_leg",
        ("quad", "quads", "quadricep", "quadriceps", "thigh", "thighs", "femur", "femoral", "it band", "iliotibial", "charley horse", "charlie horse"),
    ),
    (
        "hip_groin",
        "upper_leg",
        (
            "hip",
            "hips",
            "groin",
            "adductor",
            "adductors",
            "hip flexor",
            "flexor",
            "sports hernia",
            "hernia",
            "osteitis pubis",
            "pelvis",
            "pelvic",
            "glute",
            "gluteal",
            "gluteus",
            "buttock",
            "buttocks",
            "labrum",  # hip labrum far more common than shoulder in notes
            "piriformis",
            "sacroiliac",
            "si joint",
            "iliac",
            "pubic",
            "sacral",
            "sacrum",
        ),
    ),
    (
        "back",
        "torso",
        ("back", "spine", "spinal", "disc", "disk", "lumbar", "sciatica", "sciatic", "tailbone", "coccyx", "vertebra", "vertebrae", "spasms", "facet", "thoracic", "tail bone"),
    ),
    (
        "torso",
        "torso",
        ("rib", "ribs", "abdominal", "abdomen", "abdominals", "oblique", "core", "chest", "sternum", "pectoral", "intercostal", "stomach muscle", "side strain", "rectus abdominis", "lung", "pneumothorax", "spleen"),
    ),
    (
        "head",
        "head",
        (
            "concussion",
            "concussion-like",
            "head",
            "nose",
            "nasal",
            "eye",
            "eyes",
            "orbital",
            "face",
            "facial",
            "jaw",
            "tooth",
            "teeth",
            "dental",
            "mouth",
            "lip",
            "cheek",
            "cheekbone",
            "ear",
            "skull",
            "migraine",
            "migraines",
            "headache",
            "headaches",
            "corneal",
            "retina",
        ),
    ),
    ("neck", "torso", ("neck", "cervical", "whiplash", "stinger")),
    (
        "shoulder",
        "upper_body",
        ("shoulder", "shoulders", "rotator cuff", "clavicle", "collarbone", "ac joint", "acromioclavicular", "scapula", "deltoid", "labral", "glenoid"),
    ),
    ("arm_elbow", "upper_body", ("elbow", "elbows", "arm", "arms", "bicep", "biceps", "tricep", "triceps", "forearm", "humerus", "ulna", "radius")),
    (
        "hand_wrist",
        "upper_body",
        ("hand", "hands", "wrist", "wrists", "finger", "fingers", "thumb", "thumbs", "metacarpal", "knuckle", "pinkie", "pinky", "scaphoid", "ulnar collateral", "ucl", "ulnar styloid", "scapholunate", "tfcc", "lunate", "hamate"),
    ),
    ("leg_unspecified", "leg_unspecified", ("leg", "legs", "lower body", "lower extremity")),
)

LOCATIONS = tuple(rule[0] for rule in LOCATION_RULES) + ("other", "unspecified")
BELOW_KNEE_LOCATIONS = frozenset(rule[0] for rule in LOCATION_RULES if rule[1] == "below_knee")

# ---------------------------------------------------------------- natures
NATURE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("partial_tear", ("partial tear", "partially torn", "partial rupture", "partial-thickness tear", "grade 2 tear")),
    ("rupture", ("rupture", "ruptured", "torn", "tear", "tore", "tears")),
    ("fracture", ("fracture", "fractured", "broken", "break", "stress reaction", "hairline", "chip")),
    ("surgery", ("surgery", "surgical", "arthroscopic", "arthroscopy", "procedure", "repair", "rehab", "rehabilitation", "recovering")),
    ("dislocation", ("dislocation", "dislocated", "subluxation", "subluxed", "separated", "separation")),
    ("sprain", ("sprain", "sprained", "hyperextended", "hyperextension", "twisted")),
    ("strain", ("strain", "strained", "pulled", "pull", "tightness", "tight", "cramp", "cramps", "cramping")),
    ("contusion", ("contusion", "bruise", "bruised", "bone bruise", "hip pointer")),
    ("tendinitis", ("tendinitis", "tendonitis", "tendinopathy", "tendinosis", "fasciitis", "fasciaitis", "bursitis", "synovitis", "inflammation", "inflamed", "swelling", "swollen", "effusion")),
    ("soreness", ("sore", "soreness", "pain", "discomfort", "stiffness", "stiff", "irritation", "management", "injury management", "maintenance")),
    ("concussion", ("concussion", "concussion-like", "protocol")),
    ("infection", ("infection", "infected", "cellulitis")),
    ("illness", ("illness", "ill", "sick", "flu", "virus", "viral", "fever", "gastro", "stomach", "respiratory", "bronchitis", "strep", "pneumonia", "migraine", "food poisoning")),
)

# ---------------------------------------------------------------- categories
# Non-injury categories first, because "DNP - Injury/Illness" must not match
# "illness" alone. Each tuple: category, keywords.
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (COACH, ("coach's decision", "coachs decision", "coach decision", "coaches decision", "cd", "dnp-cd", "not in rotation")),
    (
        PROTOCOL,
        ("health and safety", "health & safety", "covid", "coronavirus", "quarantine", "contact tracing", "hsp"),
    ),
    (
        SUSPENSION,
        ("suspension", "suspended", "suspend"),
    ),
    (
        ROSTER,
        (
            "trade",
            "traded",
            "trade pending",
            "g league",
            "g-league",
            "two-way",
            "two way",
            "not with team",
            "nwt",
            "inactive",
            "league assignment",
            "assignment",
            "visa",
            "contract",
            "waived",
            "signed",
            "roster",
            "no memo",
            "not on roster",
            "transfer",
            "immigration",
            "ineligible",
        ),
    ),
    (
        PERSONAL,
        (
            "personal",
            "family",
            "death",
            "funeral",
            "birth",
            "paternity",
            "wedding",
            "bereavement",
            "excused",
            "religious",
            "court",
            "legal",
            "jury",
            "graduation",
        ),
    ),
    (
        REST,
        ("rest", "resting", "load management", "dnp - rest", "day off", "maintenance day", "return to competition", "reconditioning", "conditioning"),
    ),
)

ILLNESS_WORDS = (
    "illness",
    "ill",
    "sick",
    "flu",
    "flu-like",
    "virus",
    "viral",
    "fever",
    "gastro",
    "gastroenteritis",
    "stomach",
    "respiratory",
    "bronchitis",
    "strep",
    "pneumonia",
    "infection",
    "migraine",
    "migraines",
    "food poisoning",
    "dehydration",
    "dehydrated",
    "cold",
    "sinus",
    "chicken pox",
    "mono",
    "mononucleosis",
    "appendectomy",
    "appendicitis",
    "irregular heartbeat",
    "heart",
    "cardiac",
    "blood clot",
    "clot",
    "asthma",
    "allergic",
    "allergy",
    "allergies",
    "kidney",
    "medical",
    "non-basketball",
    "non basketball",
    "nausea",
    "vertigo",
    "tonsil",
    "tonsillitis",
    "dizziness",
    "headache",
    "headaches",
    "toothache",
    "shingles",
    "covid",
)

_PREFIX = re.compile(
    r"^\s*(dnp|dnd|nwt|dnt|inj|did not play|did not dress|not with team|out|questionable|doubtful|probable|available)(?![a-z])\s*[-–:]*\s*",
    re.IGNORECASE,
)
_SIDE = re.compile(r"\b(left|right|lt\.?|rt\.?|bilateral)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z]+(?:[-'][a-z]+)*")


@dataclass(frozen=True)
class Label:
    category: str
    location: str  # one of LOCATIONS, or "" when not an injury
    region: str  # below_knee | knee | upper_leg | torso | head | upper_body | leg_unspecified | other | unspecified | ""
    side: str  # left | right | bilateral | ""
    nature: str  # one of the NATURE_RULES names, or "" when none matched
    below_knee: bool


def normalise(text: str) -> str:
    """Lower-case, strip the DNP/DND prefix, collapse whitespace."""
    cleaned = text.strip().strip('"').strip()
    cleaned = _PREFIX.sub("", cleaned)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-word phrase match: 'arm' must not match 'warm' or 'harm'."""
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", haystack) is not None


def _first_match(text: str, rules) -> str:
    for name, *rest in rules:
        keywords = rest[-1]
        for kw in keywords:
            if _contains_phrase(text, kw):
                return name
    return ""


def classify_side(text: str) -> str:
    m = _SIDE.search(text)
    if not m:
        return ""
    s = m.group(1).lower().rstrip(".")
    return {"lt": "left", "rt": "right"}.get(s, s)


def classify_location(text: str) -> tuple[str, str]:
    """Return (location, region) for injury text, or ('unspecified', 'unspecified')."""
    for location, region, keywords in LOCATION_RULES:
        for kw in keywords:
            if _contains_phrase(text, kw):
                return location, region
    return "unspecified", "unspecified"


def classify_nature(text: str) -> str:
    return _first_match(text, NATURE_RULES)


def classify_category(text: str) -> str:
    """Category only. `text` must already be normalised."""
    if text == "":
        return UNKNOWN
    # The box-score literal "injury/illness" carries no body part and no
    # illness signal: it is its own bucket so charts can show its size.
    if text in ("injury/illness", "injury / illness", "injury-illness", "injury or illness"):
        return INJURY_UNSPECIFIED
    if text.startswith("injury/illness - ") or text.startswith("injury/illness -"):
        # Official report format: "Injury/Illness - Left Ankle; Sprain"
        body = text.split("-", 1)[1].strip()
        if any(_contains_phrase(body, w) for w in ILLNESS_WORDS) and classify_location(body)[0] == "unspecified":
            return ILLNESS
        return INJURY if body else INJURY_UNSPECIFIED
    hit = _first_match(text, CATEGORY_RULES)
    if hit:
        return hit
    location, _ = classify_location(text)
    nature = classify_nature(text)
    if location != "unspecified":
        return INJURY
    if any(_contains_phrase(text, w) for w in ILLNESS_WORDS):
        return ILLNESS
    if nature and nature not in ("illness", "concussion"):
        # "surgery", "fracture", "sprain" with no body part named
        return INJURY
    if nature == "concussion":
        return INJURY
    if "injury" in text or "injured" in text:
        return INJURY_UNSPECIFIED
    return UNKNOWN


# Categories whose free text may be published verbatim. Everything else (illness,
# personal, protocol, roster, coach, unknown) keeps its category and loses its
# text in every tracked file: the page never uses it and a relative's death, an
# arrest or an infection status is not the investigation's business.
PUBLISHABLE_TEXT_CATEGORIES = frozenset({INJURY, INJURY_UNSPECIFIED, REST, SUSPENSION})


def publishable_text(text: str, category: str) -> str:
    """The text to keep in a tracked file: unchanged for injury-type rows, blank otherwise."""
    return text if category in PUBLISHABLE_TEXT_CATEGORIES else ""


def classify(text: str | None) -> Label:
    """Map one free-text reason to a Label. Pure; never raises on odd text."""
    norm = normalise(text or "")
    category = classify_category(norm)
    if category == UNKNOWN and re.search(r"(?<![a-z])(nwt|not with team)(?![a-z])", (text or "").lower()):
        category = ROSTER
    if category == INJURY:
        body = norm.split("-", 1)[1].strip() if norm.startswith("injury/illness") and "-" in norm else norm
        location, region = classify_location(body)
        if location == "unspecified":
            location, region = "other", "other"
        return Label(
            category=category,
            location=location,
            region=region,
            side=classify_side(norm),
            nature=classify_nature(body),
            below_knee=location in BELOW_KNEE_LOCATIONS,
        )
    return Label(category=category, location="", region="", side="", nature="", below_knee=False)
