# app/taxonomy.py
"""
NTRL Canonical Manipulation Taxonomy (v1)

Defines 80+ manipulation types across 6 categories (A-F).
This is the single source of truth for manipulation type IDs.

Categories:
    A - Attention & Engagement Manipulation
    B - Emotional & Affective Manipulation
    C - Cognitive & Epistemic Manipulation
    D - Linguistic & Framing Manipulation
    E - Structural & Editorial Manipulation
    F - Incentive & Meta Manipulation

Type ID Format: {Category}.{L2}.{L3}
    Example: A.1.1 = Attention > Curiosity Gap > Curiosity gap
"""

from dataclasses import dataclass, field
from enum import Enum

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class ManipulationCategory(str, Enum):
    """Level 1 categories (A-F)"""

    ATTENTION_ENGAGEMENT = "A"  # Attention & Engagement
    EMOTIONAL_AFFECTIVE = "B"  # Emotional & Affective
    COGNITIVE_EPISTEMIC = "C"  # Cognitive & Epistemic
    LINGUISTIC_FRAMING = "D"  # Linguistic & Framing
    STRUCTURAL_EDITORIAL = "E"  # Structural & Editorial
    INCENTIVE_META = "F"  # Incentive & Meta


class SpanAction(str, Enum):
    """Action to take on a detected manipulation span"""

    REMOVE = "remove"  # Delete entirely (no factual content)
    REPLACE = "replace"  # Direct word substitution
    REWRITE = "rewrite"  # Rewrite while preserving facts
    ANNOTATE = "annotate"  # Keep text, note in transparency
    PRESERVE = "preserve"  # Keep unchanged (exemption applied)


class ArticleSegment(str, Enum):
    """Segments of an article for detection"""

    TITLE = "title"
    DECK = "deck"  # Subheadline
    LEDE = "lede"  # First paragraph
    BODY = "body"
    CAPTION = "caption"
    PULLQUOTE = "pullquote"
    EMBED = "embed"
    TABLE = "table"


# Segment severity multipliers (title manipulation is worse than body)
SEGMENT_MULTIPLIERS = {
    ArticleSegment.TITLE: 1.5,
    ArticleSegment.DECK: 1.3,
    ArticleSegment.LEDE: 1.2,
    ArticleSegment.CAPTION: 1.2,
    ArticleSegment.BODY: 1.0,
    ArticleSegment.PULLQUOTE: 0.6,  # Quotes get lower weight
    ArticleSegment.EMBED: 1.0,
    ArticleSegment.TABLE: 1.0,
}


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class ManipulationType:
    """
    Definition of a single manipulation type in the taxonomy.

    Attributes:
        type_id: Stable identifier (e.g., "A.1.1")
        category: Level 1 category (A-F)
        l2_name: Level 2 subcategory name
        l3_name: Level 3 specific type name
        label: Human-friendly display name
        description: Brief description of the manipulation
        examples: Real-world examples of this manipulation
        default_severity: Base severity level (1-5)
        default_action: Recommended action to take
        lexical_patterns: Regex patterns for lexical detection (optional)
    """

    type_id: str
    category: ManipulationCategory
    l2_name: str
    l3_name: str
    label: str
    description: str
    examples: list[str] = field(default_factory=list)
    default_severity: int = 3
    default_action: SpanAction = SpanAction.REWRITE
    lexical_patterns: list[str] = field(default_factory=list)

    @property
    def l1_name(self) -> str:
        """Human-readable L1 category name"""
        return CATEGORY_NAMES[self.category]

    @property
    def full_path(self) -> str:
        """Full taxonomy path: L1 > L2 > L3"""
        return f"{self.l1_name} > {self.l2_name} > {self.l3_name}"


@dataclass
class DetectionInstance:
    """
    A single detected manipulation instance in text.

    Attributes:
        detection_id: Unique identifier for this detection
        type_id_primary: Primary manipulation type ID
        type_ids_secondary: Additional type IDs (multi-label)
        segment: Which part of article this was found in
        span_start: Character start position in segment
        span_end: Character end position (exclusive)
        text: The exact text that was flagged
        confidence: Detection confidence (0-1)
        severity: Impact severity (1-5)
        severity_weighted: After segment multiplier applied
        rationale: Brief explanation of why this was flagged
        recommended_action: Suggested action to take
        rewrite_template_id: Template to use for rewriting (optional)
        detector_source: Which detector found this (lexical/structural/semantic)
        exemptions_applied: Any guardrails that prevented action
    """

    detection_id: str
    type_id_primary: str
    segment: ArticleSegment
    span_start: int
    span_end: int
    text: str
    confidence: float
    severity: int
    detector_source: str
    type_ids_secondary: list[str] = field(default_factory=list)
    severity_weighted: float = 0.0
    rationale: str = ""
    recommended_action: SpanAction = SpanAction.REWRITE
    rewrite_template_id: str | None = None
    exemptions_applied: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Category Names
# -----------------------------------------------------------------------------

CATEGORY_NAMES = {
    ManipulationCategory.ATTENTION_ENGAGEMENT: "Attention & Engagement",
    ManipulationCategory.EMOTIONAL_AFFECTIVE: "Emotional & Affective",
    ManipulationCategory.COGNITIVE_EPISTEMIC: "Cognitive & Epistemic",
    ManipulationCategory.LINGUISTIC_FRAMING: "Linguistic & Framing",
    ManipulationCategory.STRUCTURAL_EDITORIAL: "Structural & Editorial",
    ManipulationCategory.INCENTIVE_META: "Incentive & Meta",
}


# -----------------------------------------------------------------------------
# Full Taxonomy Registry (80+ Types)
# -----------------------------------------------------------------------------

MANIPULATION_TAXONOMY: dict[str, ManipulationType] = {
    # =========================================================================
    # A. ATTENTION & ENGAGEMENT MANIPULATION
    # =========================================================================
    # A.1 Curiosity Gap / Engagement Hooks
    "A.1.1": ManipulationType(
        type_id="A.1.1",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Curiosity Gap",
        l3_name="Curiosity gap",
        label="Curiosity gap",
        description="Withholds key information to create artificial suspense",
        examples=["You won't believe what investigators found."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"you won'?t believe",
            r"can'?t believe what",
            r"what happened next",
            r"the reason (why )?(will|might) (shock|surprise|amaze)",
        ],
    ),
    "A.1.2": ManipulationType(
        type_id="A.1.2",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Curiosity Gap",
        l3_name="Open-loop teaser",
        label="Open-loop teaser",
        description="Creates unresolved tension to keep reader engaged",
        examples=["One detail changes everything—but it's not what you think."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"but it'?s not what you think",
            r"one (thing|detail) changes everything",
            r"here'?s (the|what) .{0,20} (catch|twist)",
            r"wait until you (see|hear|read)",
        ],
    ),
    "A.1.3": ManipulationType(
        type_id="A.1.3",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Curiosity Gap",
        l3_name="Withheld key fact",
        label="Withheld key fact",
        description="Omits crucial who/what/when to create mystery",
        examples=["A major company made a huge move today."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"a (major|top|leading) (company|official|source)",
            r"(someone|something) (big|major|important)",
            r"a (huge|major|big) (move|change|announcement)",
        ],
    ),
    "A.1.4": ManipulationType(
        type_id="A.1.4",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Curiosity Gap",
        l3_name="Rhetorical-question hook",
        label="Rhetorical-question hook",
        description="Uses provocative questions to imply conclusions",
        examples=["Is your job about to disappear?"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"is your .{1,30}\?$",
            r"are you .{1,30}\?$",
            r"could this .{1,30}\?$",
            r"what if .{1,30}\?$",
        ],
    ),
    "A.1.5": ManipulationType(
        type_id="A.1.5",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Curiosity Gap",
        l3_name="Cliffhanger pacing",
        label="Cliffhanger pacing",
        description="Narrative structure designed to maintain suspense",
        examples=["But the most surprising part came later…"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"but (the|that) .{0,20} (came|happened) (next|later)",
            r"(and )?then .{0,20} happened",
            r"what (came|happened) next",
        ],
    ),
    # A.2 Urgency / Time Manipulation
    "A.2.1": ManipulationType(
        type_id="A.2.1",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Urgency Inflation",
        l3_name="Urgency inflation",
        label="Urgency inflation",
        description="Creates false sense of immediate importance",
        examples=["BREAKING: Everything is changing right now."],
        default_severity=4,
        default_action=SpanAction.REMOVE,
        lexical_patterns=[
            r"\bBREAKING\b",
            r"\bJUST IN\b",
            r"\bURGENT\b",
            r"\bDEVELOPING\b",
            r"\bALERT\b",
            r"right now",
            r"as we speak",
        ],
    ),
    "A.2.2": ManipulationType(
        type_id="A.2.2",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Urgency Inflation",
        l3_name="False immediacy",
        label="False immediacy",
        description="Presents old information as if it's new",
        examples=["Just in: new details (details are from last week)"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"just in:",
            r"new details (emerge|surface)",
            r"latest (news|update|development)",
        ],
    ),
    "A.2.3": ManipulationType(
        type_id="A.2.3",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Urgency Inflation",
        l3_name="Deadline pressure",
        label="Deadline pressure",
        description="Creates artificial time pressure on reader",
        examples=["Act now before it's too late."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"act now",
            r"before it'?s too late",
            r"don'?t wait",
            r"time is running out",
            r"last chance",
        ],
    ),
    "A.2.4": ManipulationType(
        type_id="A.2.4",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Urgency Inflation",
        l3_name="Scarcity framing",
        label="Scarcity framing",
        description="Creates artificial sense of limited availability",
        examples=["Only a short window remains."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"only .{0,20} (left|remain)",
            r"short window",
            r"limited time",
            r"while (supplies|it) last",
        ],
    ),
    "A.2.5": ManipulationType(
        type_id="A.2.5",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Urgency Inflation",
        l3_name="Time-compression",
        label="Time-compression",
        description="Compresses timeline to create false urgency",
        examples=["Overnight, the situation spiraled… (actually months)"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"overnight",
            r"suddenly",
            r"in (just )?(hours|days)",
            r"spiraled",
        ],
    ),
    # A.3 Social Proof / Virality
    "A.3.1": ManipulationType(
        type_id="A.3.1",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Virality substitution",
        label="Virality substitution",
        description="Uses viral spread as substitute for importance",
        examples=["This is going viral for a reason."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"going viral",
            r"breaking the internet",
            r"everyone is (talking|sharing)",
        ],
    ),
    "A.3.2": ManipulationType(
        type_id="A.3.2",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Trending-as-importance",
        label="Trending-as-importance",
        description="Equates trending status with newsworthiness",
        examples=["The internet can't stop talking about…"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(the )?internet can'?t stop",
            r"trending (on|across)",
            r"taking (over )?(the internet|social media)",
        ],
    ),
    "A.3.3": ManipulationType(
        type_id="A.3.3",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Comment-bait framing",
        label="Comment-bait framing",
        description="Frames story to maximize engagement/comments",
        examples=["People are divided over this one issue."],
        default_severity=2,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"people are divided",
            r"(this|the) debate",
            r"what do you think",
        ],
    ),
    "A.3.4": ManipulationType(
        type_id="A.3.4",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Reaction-first journalism",
        label="Reaction-first journalism",
        description="Story is primarily about reactions, not events",
        examples=["Outrage erupts after… (story is mostly outrage quotes)"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"outrage (erupts|explodes|grows)",
            r"backlash (grows|mounts|erupts)",
            r"(twitter|social media) (reacts|responds|erupts)",
        ],
    ),
    "A.3.5": ManipulationType(
        type_id="A.3.5",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Screenshot journalism",
        label="Screenshot journalism",
        description="Treats social media posts as primary news events",
        examples=["A tweet sparked backlash… treated as primary event"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"a (tweet|post) (sparked|caused|led to)",
            r"(tweet|post) went viral",
        ],
    ),
    "A.3.6": ManipulationType(
        type_id="A.3.6",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Social Proof",
        l3_name="Outrage laundering",
        label="Outrage laundering",
        description="Republishes extreme content 'to condemn it' while amplifying",
        examples=["Republishing an extreme post 'to condemn it,' amplifying it"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    # A.4 Sensational Formatting
    "A.4.1": ManipulationType(
        type_id="A.4.1",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Sensational Formatting",
        l3_name="Sensational formatting",
        label="Sensational formatting",
        description="Uses excessive punctuation/formatting for emphasis",
        examples=["THIS CHANGES EVERYTHING!!!"],
        default_severity=3,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"!!+",
            r"\?\?+",
            r"!+\?+",
        ],
    ),
    "A.4.2": ManipulationType(
        type_id="A.4.2",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Sensational Formatting",
        l3_name="ALL CAPS emphasis",
        label="ALL CAPS emphasis",
        description="Uses all caps for artificial emphasis",
        examples=["SHOCKING footage shows…"],
        default_severity=3,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            # Note: This pattern requires CASE_SENSITIVE flag (handled in detector)
            r"(?-i:\b[A-Z]{4,}\b)",  # 4+ consecutive caps (case-sensitive)
        ],
    ),
    "A.4.3": ManipulationType(
        type_id="A.4.3",
        category=ManipulationCategory.ATTENTION_ENGAGEMENT,
        l2_name="Sensational Formatting",
        l3_name="Excess punctuation",
        label="Excess punctuation",
        description="Uses multiple punctuation marks for drama",
        examples=["How did this happen?!"],
        default_severity=2,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"[!?]{2,}",
        ],
    ),
    # =========================================================================
    # B. EMOTIONAL & AFFECTIVE MANIPULATION
    # =========================================================================
    # B.1 Fear Appeals
    "B.1.1": ManipulationType(
        type_id="B.1.1",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Fear Appeals",
        l3_name="Fear appeal",
        label="Fear appeal",
        description="Invokes fear without proportionate factual basis",
        examples=["This could put your family at risk."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"put.{0,20}at risk",
            r"threaten.{0,20}(safety|security|life)",
            r"danger.{0,20}(lurks|looms|awaits)",
        ],
    ),
    "B.1.2": ManipulationType(
        type_id="B.1.2",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Fear Appeals",
        l3_name="Catastrophizing",
        label="Catastrophizing",
        description="Presents worst-case scenarios as likely or inevitable",
        examples=["The system is on the verge of collapse."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"on the verge of",
            r"brink of (collapse|disaster|crisis)",
            r"headed for (disaster|catastrophe)",
            r"(total|complete|utter) (collapse|failure|disaster)",
        ],
    ),
    "B.1.3": ManipulationType(
        type_id="B.1.3",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Fear Appeals",
        l3_name="Existential threat framing",
        label="Existential threat framing",
        description="Frames issues as threats to existence or way of life",
        examples=["Democracy is dying in real time."],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"democracy is (dying|dead|under attack)",
            r"end of.{0,20}as we know it",
            r"existential threat",
            r"(threatens|destroys) everything",
        ],
    ),
    "B.1.4": ManipulationType(
        type_id="B.1.4",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Fear Appeals",
        l3_name="Panic language",
        label="Panic language",
        description="Uses panic/fear terms to describe situations",
        examples=["Markets panic as fear spreads."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\bpanic\b",
            r"fear (spreads|grows|grips)",
            r"terror (grips|spreads)",
            r"chaos (erupts|ensues|unfolds)",
        ],
    ),
    "B.1.5": ManipulationType(
        type_id="B.1.5",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Fear Appeals",
        l3_name="Personal vulnerability targeting",
        label="Personal vulnerability targeting",
        description="Directly targets reader's personal fears",
        examples=["You could be next."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"you could be next",
            r"it could happen to you",
            r"your (family|children|home).{0,20}(risk|danger|threat)",
        ],
    ),
    # B.2 Anger/Outrage Engineering
    "B.2.1": ManipulationType(
        type_id="B.2.1",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Anger/Outrage",
        l3_name="Anger/outrage engineering",
        label="Anger/outrage engineering",
        description="Deliberately provokes anger without proportionate cause",
        examples=["People are furious after officials…"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"people are (furious|outraged|angry)",
            r"(fury|outrage|anger) (erupts|grows|mounts)",
            r"sparks? (fury|outrage|anger)",
        ],
    ),
    "B.2.2": ManipulationType(
        type_id="B.2.2",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Anger/Outrage",
        l3_name="Rage verbs",
        label="Rage verbs",
        description="Uses violent/aggressive verbs to describe speech acts",
        examples=["Leader SLAMS critics in brutal takedown."],
        default_severity=4,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"\bslams?\b",
            r"\bblasts?\b",
            r"\bdestroys?\b",
            r"\beviscerates?\b",
            r"\bobliterates?\b",
            r"\bannihilates?\b",
            r"\btorches?\b",
            r"\brips?\b",
            r"\bshreds?\b",
            r"takedown",
            r"claps? back",
        ],
    ),
    "B.2.3": ManipulationType(
        type_id="B.2.3",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Anger/Outrage",
        l3_name="Moral violation loading",
        label="Moral violation loading",
        description="Frames actions as moral violations to provoke outrage",
        examples=["A disgraceful betrayal of the public."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\bdisgraceful\b",
            r"\bbetrayal\b",
            r"\bunforgivable\b",
            r"\binexcusable\b",
            r"\breprehensible\b",
        ],
    ),
    "B.2.4": ManipulationType(
        type_id="B.2.4",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Anger/Outrage",
        l3_name="Humiliation/dominance framing",
        label="Humiliation/dominance framing",
        description="Frames interactions as dominance/humiliation",
        examples=["They got owned on live TV."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\bgot owned\b",
            r"\bhumiliated\b",
            r"\bembarrassed\b",
            r"\bschooled\b",
            r"\bdestroyed\b",
        ],
    ),
    "B.2.5": ManipulationType(
        type_id="B.2.5",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Anger/Outrage",
        l3_name="Scapegoating",
        label="Scapegoating",
        description="Assigns blame to a group without evidence",
        examples=["This is happening because of them."],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"because of (them|these people|those)",
            r"(they|them|those people) are (responsible|to blame)",
        ],
    ),
    # B.3 Shame/Guilt Coercion
    "B.3.1": ManipulationType(
        type_id="B.3.1",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Shame/Guilt",
        l3_name="Shame coercion",
        label="Shame coercion",
        description="Uses shame to pressure reader into agreement",
        examples=["If you're not outraged, you're the problem."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"if you'?re not .{0,20} you'?re (the problem|part of)",
            r"shame on (you|anyone)",
            r"should be ashamed",
        ],
    ),
    "B.3.2": ManipulationType(
        type_id="B.3.2",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Shame/Guilt",
        l3_name="Guilt coercion",
        label="Guilt coercion",
        description="Uses guilt to pressure reader into action",
        examples=["How can anyone stay silent?"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"how can (anyone|you) (stay silent|ignore)",
            r"blood on .{0,20} hands",
            r"complicit in",
        ],
    ),
    "B.3.3": ManipulationType(
        type_id="B.3.3",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Shame/Guilt",
        l3_name="Purity policing",
        label="Purity policing",
        description="Defines in-group membership through ideological purity",
        examples=["Real supporters would never accept this."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"real (supporters|americans|patriots|believers)",
            r"true (believers|patriots|fans)",
            r"would never accept",
        ],
    ),
    # B.4 Identity/Tribal Priming
    "B.4.1": ManipulationType(
        type_id="B.4.1",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Identity/Tribal",
        l3_name="Identity/tribal priming",
        label="Identity/tribal priming",
        description="Activates group identity to influence perception",
        examples=["Real Americans are fed up."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"real americans",
            r"hardworking (americans|families|people)",
            r"ordinary (people|citizens|americans)",
        ],
    ),
    "B.4.2": ManipulationType(
        type_id="B.4.2",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Identity/Tribal",
        l3_name="In-group virtue vs out-group blame",
        label="In-group virtue vs out-group blame",
        description="Contrasts virtuous in-group with blamed out-group",
        examples=["Hardworking families vs out-of-touch elites."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"out-of-touch (elites|officials|politicians)",
            r"(the|these) elites",
            r"vs\.? .{0,20}(elites|establishment)",
        ],
    ),
    "B.4.3": ManipulationType(
        type_id="B.4.3",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Identity/Tribal",
        l3_name="Proxy-coded identity triggers",
        label="Proxy-coded identity triggers",
        description="Uses coded language to invoke group identity",
        examples=["Coastal elites", "woke mob", "taxpayer revolt"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"coastal elites?",
            r"woke (mob|crowd|left)",
            r"taxpayer revolt",
            r"silent majority",
            r"mainstream media",
        ],
    ),
    "B.4.4": ManipulationType(
        type_id="B.4.4",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Identity/Tribal",
        l3_name="Status threat framing",
        label="Status threat framing",
        description="Frames change as threat to group's status/identity",
        examples=["They're coming for your way of life."],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"coming for your",
            r"(take|destroy|ruin) (your|our) way of life",
            r"under attack",
        ],
    ),
    # B.5 Sentiment Steering
    "B.5.1": ManipulationType(
        type_id="B.5.1",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Sentiment Steering",
        l3_name="Sentiment steering adverbs",
        label="Sentiment steering adverbs",
        description="Uses adverbs to steer reader's emotional response",
        examples=["Alarmingly, the pattern continues…"],
        default_severity=3,
        default_action=SpanAction.REMOVE,
        lexical_patterns=[
            r"\balarmingly\b",
            r"\bshockingly\b",
            r"\bstunningly\b",
            r"\bdisturbingly\b",
            r"\bterrifyingly\b",
            r"\bhorrifyingly\b",
            r"\btragically\b",
        ],
    ),
    "B.5.2": ManipulationType(
        type_id="B.5.2",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Sentiment Steering",
        l3_name="Emotional cadence",
        label="Emotional cadence",
        description="Uses rhythmic repetition for emotional effect",
        examples=["No answers. No accountability. No shame."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"no \w+\. no \w+\. no \w+",
            r"(again|still|yet) and (again|still|yet)",
        ],
    ),
    "B.5.3": ManipulationType(
        type_id="B.5.3",
        category=ManipulationCategory.EMOTIONAL_AFFECTIVE,
        l2_name="Sentiment Steering",
        l3_name="Sentimentalization",
        label="Sentimentalization",
        description="Excessive emotional appeals not supported by facts",
        examples=["Heartbreaking scenes will leave you in tears."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"heartbreaking",
            r"leave you in tears",
            r"will (break|melt) your heart",
            r"(gut-wrenching|soul-crushing)",
        ],
    ),
    # =========================================================================
    # C. COGNITIVE & EPISTEMIC MANIPULATION
    # =========================================================================
    # C.1 Certainty Manipulation
    "C.1.1": ManipulationType(
        type_id="C.1.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Certainty Manipulation",
        l3_name="Certainty inflation",
        label="Certainty inflation",
        description="Presents uncertain claims as definitively settled",
        examples=["This definitively settles the debate."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"definitively (settles|proves|confirms)",
            r"once and for all",
            r"beyond (any )?(doubt|question)",
            r"indisputably",
        ],
    ),
    "C.1.2": ManipulationType(
        type_id="C.1.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Certainty Manipulation",
        l3_name="Absolutist verbs",
        label="Absolutist verbs",
        description="Uses absolute verbs for uncertain claims",
        examples=["Proves", "debunks", "destroys", "confirms"],
        default_severity=4,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"\bproves?\b",
            r"\bdebunks?\b",
            r"\bdestroys?\b",
            r"\bconfirms?\b",
            r"\bexposes?\b",
            r"\breveals? the truth\b",
        ],
    ),
    "C.1.3": ManipulationType(
        type_id="C.1.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Certainty Manipulation",
        l3_name="Premature narrative closure",
        label="Premature narrative closure",
        description="Presents conclusions before facts are established",
        examples=["Here's what it all means before facts stabilize"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"here'?s what (it all|this) means",
            r"the (real|true) (story|meaning)",
            r"what we (now )?know for sure",
        ],
    ),
    "C.1.4": ManipulationType(
        type_id="C.1.4",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Certainty Manipulation",
        l3_name="Retrospective inevitability",
        label="Retrospective inevitability",
        description="Presents past events as if they were predictable",
        examples=["It was obvious this would happen."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"it was (obvious|inevitable|clear)",
            r"should have seen (this|it) coming",
            r"we all knew",
        ],
    ),
    # C.2 Speculation/Intent Attribution
    "C.2.1": ManipulationType(
        type_id="C.2.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Speculation",
        l3_name="Speculation laundering",
        label="Speculation laundering",
        description="Presents speculation as the main claim",
        examples=["Sources suggest… as the main claim"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"sources (suggest|say|indicate)",
            r"(it'?s|it is) (believed|thought|understood)",
            r"reportedly",
        ],
    ),
    "C.2.2": ManipulationType(
        type_id="C.2.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Speculation",
        l3_name="Hypothetical stacking",
        label="Hypothetical stacking",
        description="Stacks hypotheticals to imply likelihood",
        examples=["Could potentially soon… implying likelihood"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"could (potentially|possibly|perhaps)",
            r"might (soon|eventually|possibly)",
            r"may (well|potentially|possibly)",
        ],
    ),
    "C.2.3": ManipulationType(
        type_id="C.2.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Speculation",
        l3_name="Motive certainty",
        label="Motive certainty",
        description="Presents inferred motives as known facts",
        examples=["They did this to silence critics."],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(they|he|she) did this to",
            r"(their|his|her) (real|true) motive",
            r"the (real|true) reason (is|was)",
        ],
    ),
    "C.2.4": ManipulationType(
        type_id="C.2.4",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Speculation",
        l3_name="Intent attribution",
        label="Intent attribution",
        description="Attributes intent without evidence",
        examples=["Officials want you to be scared."],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(they|officials|the government) want(s)? you to",
            r"designed to (make|keep|scare)",
            r"meant to (deceive|manipulate|control)",
        ],
    ),
    # C.3 Evidence Distortion
    "C.3.1": ManipulationType(
        type_id="C.3.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Evidence distortion",
        label="Evidence distortion",
        description="Misleading presentation of statistical evidence",
        examples=["Crime up 200%! (from 1 to 3)"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\d+%\s*(increase|rise|jump|spike|surge)",
            r"(doubled|tripled|quadrupled)",
        ],
    ),
    "C.3.2": ManipulationType(
        type_id="C.3.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Cherry-picking",
        label="Cherry-picking",
        description="Selects favorable data window to support claim",
        examples=["Selecting a favorable window to claim 'surge'"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "C.3.3": ManipulationType(
        type_id="C.3.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Misleading denominators",
        label="Misleading denominators",
        description="Uses misleading base for percentages",
        examples=["Half of users… from a tiny subgroup"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"(half|most|majority) of (users|people|respondents)",
        ],
    ),
    "C.3.4": ManipulationType(
        type_id="C.3.4",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Base-rate neglect",
        label="Base-rate neglect",
        description="Ignores base rates when presenting risk/frequency",
        examples=["Rare events framed as common"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "C.3.5": ManipulationType(
        type_id="C.3.5",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Correlation→causation",
        label="Correlation→causation",
        description="Presents correlation as proof of causation",
        examples=["X causes Y from correlational data"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"causes?",
            r"leads? to",
            r"results? in",
        ],
    ),
    "C.3.6": ManipulationType(
        type_id="C.3.6",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Anecdote-as-proof",
        label="Anecdote-as-proof",
        description="Uses single case as evidence for general claim",
        examples=["One vivid case treated as typical"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "C.3.7": ManipulationType(
        type_id="C.3.7",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Single-study overreach",
        label="Single-study overreach",
        description="Overstates conclusions from single unreplicated study",
        examples=["A new study proves… without replication"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(a|new|recent) study (proves|shows|confirms)",
            r"scientists? (prove|confirm|discover)",
        ],
    ),
    "C.3.8": ManipulationType(
        type_id="C.3.8",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Misleading averages",
        label="Misleading averages",
        description="Uses mean when median would be more accurate",
        examples=["Average wages rose while median fell"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"average (wage|salary|income|price)",
        ],
    ),
    "C.3.9": ManipulationType(
        type_id="C.3.9",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Selection/survivorship bias",
        label="Selection/survivorship bias",
        description="Only counts successes, ignoring failures",
        examples=["Most startups succeed (counting only funded survivors)"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "C.3.10": ManipulationType(
        type_id="C.3.10",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Evidence Distortion",
        l3_name="Methodological opacity",
        label="Methodological opacity",
        description="Cites study without methodology details",
        examples=["A study found… (no sample, method, margin of error)"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"(a|the) study (found|showed|suggests)",
            r"research (shows|suggests|indicates)",
        ],
    ),
    # C.4 Authority Manipulation
    "C.4.1": ManipulationType(
        type_id="C.4.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="Authority laundering",
        label="Authority laundering",
        description="Claims expert consensus without citation",
        examples=["Experts agree… with no citation"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"experts? (agree|say|believe|warn)",
            r"scientists? (agree|say|believe|warn)",
            r"doctors? (agree|say|recommend)",
        ],
    ),
    "C.4.2": ManipulationType(
        type_id="C.4.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="Vague authority",
        label="Vague authority",
        description="Cites unspecified authorities",
        examples=["Officials say", "observers believe"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"officials? say",
            r"observers? (believe|say|note)",
            r"sources? say",
            r"some (say|believe|argue)",
        ],
    ),
    "C.4.3": ManipulationType(
        type_id="C.4.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="Anonymous-source inflation",
        label="Anonymous-source inflation",
        description="Overreliance on anonymous sources",
        examples=["People familiar with the matter… repeatedly"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"(people|sources?) familiar with",
            r"according to (sources?|people) (who|with)",
            r"speaking on (condition of )?anonymity",
        ],
    ),
    "C.4.4": ManipulationType(
        type_id="C.4.4",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="Credential laundering",
        label="Credential laundering",
        description="Cites credentials without specifics",
        examples=["A top doctor says… (no name/field)"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"a (top|leading|prominent|renowned) (doctor|scientist|expert)",
            r"a (senior|high-ranking) official",
        ],
    ),
    "C.4.5": ManipulationType(
        type_id="C.4.5",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="False consensus",
        label="False consensus",
        description="Claims settled science when debate exists",
        examples=["Science is settled when it isn't"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(the )?science is settled",
            r"scientific consensus",
            r"all (scientists?|experts?) agree",
        ],
    ),
    "C.4.6": ManipulationType(
        type_id="C.4.6",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Authority Manipulation",
        l3_name="Process laundering",
        label="Process laundering",
        description="Cites report/study without vetting quality",
        examples=["A report says… (report quality is unvetted)"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"a (new |recent )?(report|study|analysis) (says|shows|finds)",
        ],
    ),
    # C.5 Trust/Epistemic Posture
    "C.5.1": ManipulationType(
        type_id="C.5.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Trust Manipulation",
        l3_name="Trust posture manipulation",
        label="Trust posture manipulation",
        description="Claims special access to truth",
        examples=["Only we're brave enough to report this."],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"only we",
            r"(brave|courageous) enough to",
            r"what (they|the media) won'?t tell you",
        ],
    ),
    "C.5.2": ManipulationType(
        type_id="C.5.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Trust Manipulation",
        l3_name="Epistemic intimidation",
        label="Epistemic intimidation",
        description="Uses insults to shut down questioning",
        examples=["Only idiots deny…"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"only (idiots?|fools?|morons?) (deny|believe|think)",
            r"anyone with (half )?a brain",
            r"you'?d have to be (stupid|dumb|crazy)",
        ],
    ),
    "C.5.3": ManipulationType(
        type_id="C.5.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Trust Manipulation",
        l3_name="Preemptive defensiveness",
        label="Preemptive defensiveness",
        description="Anticipates criticism to deflect scrutiny",
        examples=["They'll attack us for saying this…"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"they'?ll (attack|criticize|condemn) us for",
            r"(the media|critics?) will (try to|attempt to)",
        ],
    ),
    "C.5.4": ManipulationType(
        type_id="C.5.4",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Trust Manipulation",
        l3_name="Just asking questions",
        label="Just asking questions",
        description="Uses questions to imply without asserting",
        examples=["We're just asking: what are they hiding?"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(just|only) asking (questions|the question)",
            r"what are they hiding",
            r"makes you wonder",
        ],
    ),
    # C.6 False Balance
    "C.6.1": ManipulationType(
        type_id="C.6.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="False Balance",
        l3_name="False balance",
        label="False balance",
        description="Treats evidence-based and baseless claims as equal",
        examples=["Evidence-based claim paired with baseless claim as equal"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "C.6.2": ManipulationType(
        type_id="C.6.2",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="False Balance",
        l3_name="Weight equalization",
        label="Weight equalization",
        description="Gives fringe views equal credibility",
        examples=["Fringe view given equal credibility/time"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"on the other (hand|side)",
            r"but (critics|skeptics|others) (say|argue|believe)",
        ],
    ),
    "C.6.3": ManipulationType(
        type_id="C.6.3",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="False Balance",
        l3_name="Uncertainty equalization",
        label="Uncertainty equalization",
        description="Treats strong and weak evidence as equally uncertain",
        examples=["Strong vs weak evidence treated as same confidence"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    # C.7 Translation Bias
    "C.7.1": ManipulationType(
        type_id="C.7.1",
        category=ManipulationCategory.COGNITIVE_EPISTEMIC,
        l2_name="Translation Bias",
        l3_name="Translation/interpretation bias",
        label="Translation/interpretation bias",
        description="Translation implies meaning not in original",
        examples=["He 'admitted'… (translation implies guilt not in original)"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"admitted",  # Context-dependent
            r"confessed",
        ],
    ),
    # =========================================================================
    # D. LINGUISTIC & FRAMING MANIPULATION
    # =========================================================================
    # D.1 Loaded Language
    "D.1.1": ManipulationType(
        type_id="D.1.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Loaded Language",
        l3_name="Loaded adjectives/adverbs",
        label="Loaded adjectives/adverbs",
        description="Uses value-laden modifiers to steer perception",
        examples=["A stunning failure", "a brazen move"],
        default_severity=3,
        default_action=SpanAction.REMOVE,
        lexical_patterns=[
            r"\bstunning\b",
            r"\bbrazen\b",
            r"\bshocking\b",
            r"\bappalling\b",
            r"\boutrageous\b",
            r"\bdamning\b",
            r"\bdevastating\b",
        ],
    ),
    "D.1.2": ManipulationType(
        type_id="D.1.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Loaded Language",
        l3_name="Dysphemism",
        label="Dysphemism",
        description="Uses harsher terms than warranted",
        examples=["Regime instead of government"],
        default_severity=4,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"\bregime\b",
            r"\bjunta\b",
            r"\bcartel\b",
        ],
    ),
    "D.1.3": ManipulationType(
        type_id="D.1.3",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Loaded Language",
        l3_name="Euphemism",
        label="Euphemism",
        description="Uses softer terms than warranted",
        examples=["Irregularities instead of fraud allegations"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"\birregularities\b",
            r"\benhanced interrogation\b",
            r"\bcollateral damage\b",
        ],
    ),
    "D.1.4": ManipulationType(
        type_id="D.1.4",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Loaded Language",
        l3_name="Dehumanization",
        label="Dehumanization",
        description="Uses language that dehumanizes people",
        examples=["Vermin", "animals", "invaders"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\bvermin\b",
            r"\banimals?\b",  # Context-dependent
            r"\binvaders?\b",
            r"\bparasites?\b",
            r"\binfestations?\b",
        ],
    ),
    "D.1.5": ManipulationType(
        type_id="D.1.5",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Loaded Language",
        l3_name="Contamination metaphors",
        label="Contamination metaphors",
        description="Uses disease/contamination language for people/ideas",
        examples=["Infested", "poisoned", "infected"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\binfested\b",
            r"\bpoisoned\b",
            r"\binfected\b",
            r"\bcontaminated\b",
            r"\bplague\b",
        ],
    ),
    # D.2 Metaphor Escalation
    "D.2.1": ManipulationType(
        type_id="D.2.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Metaphor Escalation",
        l3_name="Metaphor escalation (war)",
        label="Metaphor escalation (war)",
        description="Uses war metaphors for non-war situations",
        examples=["Under siege", "battle lines drawn"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"under (siege|attack|fire)",
            r"battle lines",
            r"war (on|against)",
            r"(front|battle)lines?",
            r"(ground zero|combat zone)",
        ],
    ),
    "D.2.2": ManipulationType(
        type_id="D.2.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Metaphor Escalation",
        l3_name="Metaphor escalation (crime/chaos)",
        label="Metaphor escalation (crime/chaos)",
        description="Uses crime/chaos metaphors excessively",
        examples=["City spirals into lawlessness"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"spirals? into",
            r"lawlessness",
            r"(crime|chaos) (wave|epidemic)",
            r"(descends?|plunges?) into (chaos|anarchy)",
        ],
    ),
    "D.2.3": ManipulationType(
        type_id="D.2.3",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Metaphor Escalation",
        l3_name="Metaphor escalation (sports/fight)",
        label="Metaphor escalation (sports/fight)",
        description="Uses fight/sports metaphors for debate",
        examples=["Knockout blow", "crushed"],
        default_severity=3,
        default_action=SpanAction.REPLACE,
        lexical_patterns=[
            r"knockout (blow|punch)",
            r"\bcrushed\b",
            r"\btrounced\b",
            r"\bdominated\b",
            r"body blow",
        ],
    ),
    # D.3 Agency Hiding
    "D.3.1": ManipulationType(
        type_id="D.3.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Agency Hiding",
        l3_name="Passive voice to hide agency",
        label="Passive voice to hide agency",
        description="Uses passive voice to obscure who did what",
        examples=["Mistakes were made."],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"mistakes were made",
            r"was (done|decided|approved)",
            r"were (taken|made|implemented)",
        ],
    ),
    "D.3.2": ManipulationType(
        type_id="D.3.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Agency Hiding",
        l3_name="Agent deletion",
        label="Agent deletion",
        description="Completely removes the actor from the sentence",
        examples=["A decision was made (no actor)"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[],  # Requires structural detection
    ),
    "D.3.3": ManipulationType(
        type_id="D.3.3",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Agency Hiding",
        l3_name="Procedural fog",
        label="Procedural fog",
        description="Uses bureaucratic language to obscure actions",
        examples=["Operational adjustments were implemented"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"operational (adjustments|changes)",
            r"(policy|strategic) (adjustments|realignment)",
            r"were (implemented|executed|undertaken)",
        ],
    ),
    # D.4 Presupposition/Implicature
    "D.4.1": ManipulationType(
        type_id="D.4.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Presupposition",
        l3_name="Presupposition trap",
        label="Presupposition trap",
        description="Question presupposes contested claim",
        examples=["Why did officials fail to act?"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"why did .{0,30} fail",
            r"when will .{0,30} (admit|acknowledge|confess)",
        ],
    ),
    "D.4.2": ManipulationType(
        type_id="D.4.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Presupposition",
        l3_name="Complex question",
        label="Complex question",
        description="Question bundles contested assumptions",
        examples=["How long have they been hiding this?"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"how long have .{0,30} been (hiding|covering|lying)",
            r"when did .{0,30} (start|begin) (hiding|covering)",
        ],
    ),
    "D.4.3": ManipulationType(
        type_id="D.4.3",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Presupposition",
        l3_name="Implicature loading",
        label="Implicature loading",
        description="Language implies more than it states",
        examples=["Even he admitted…"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"even (he|she|they) (admitted|acknowledged)",
            r"finally (admitted|acknowledged|conceded)",
        ],
    ),
    "D.4.4": ManipulationType(
        type_id="D.4.4",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Presupposition",
        l3_name="Scare quotes",
        label="Scare quotes",
        description="Uses quotes to cast doubt without argument",
        examples=["The 'expert' claimed…"],
        default_severity=3,
        default_action=SpanAction.REMOVE,
        lexical_patterns=[
            r"[\"']expert[\"']",
            r"[\"']scientist[\"']",
            r"so-called",
        ],
    ),
    # D.5 Vagueness
    "D.5.1": ManipulationType(
        type_id="D.5.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Vagueness",
        l3_name="Soft quantifiers",
        label="Soft quantifiers",
        description="Uses vague quantity words instead of specifics",
        examples=["Some", "many", "a number of"],
        default_severity=2,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"\bsome (say|believe|argue|experts?)\b",
            r"\bmany (say|believe|argue|experts?)\b",
            r"a number of",
        ],
    ),
    "D.5.2": ManipulationType(
        type_id="D.5.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Vagueness",
        l3_name="Temporal vagueness",
        label="Temporal vagueness",
        description="Uses vague time references",
        examples=["Recently", "in recent years"],
        default_severity=2,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"\brecently\b",
            r"in recent (years|months|weeks)",
            r"over the (past|last) (few|several)",
        ],
    ),
    "D.5.3": ManipulationType(
        type_id="D.5.3",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Vagueness",
        l3_name="Scope ambiguity",
        label="Scope ambiguity",
        description="Unclear scope of claim (where? when? who?)",
        examples=["Impacts millions (where? when?)"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"impacts? (millions|thousands|countless)",
            r"affects? (millions|thousands|countless)",
        ],
    ),
    "D.5.4": ManipulationType(
        type_id="D.5.4",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Vagueness",
        l3_name="Absolutes",
        label="Absolutes",
        description="Uses absolute terms that are rarely accurate",
        examples=["Everyone", "no one", "always", "never"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"\beveryone (knows|agrees|believes)\b",
            r"\bno one (believes|thinks|wants)\b",
            r"\balways\b",
            r"\bnever\b",
        ],
    ),
    # D.6 Humor/Sarcasm Shield
    "D.6.1": ManipulationType(
        type_id="D.6.1",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Humor/Sarcasm",
        l3_name="Humor/sarcasm shield",
        label="Humor/sarcasm shield",
        description="Uses sarcasm to make claims while denying responsibility",
        examples=["Sure, it's 'just a coincidence.'"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"sure,? it'?s (just|only) a",
            r"what a (coincidence|surprise)",
            r"nothing to see here",
        ],
    ),
    "D.6.2": ManipulationType(
        type_id="D.6.2",
        category=ManipulationCategory.LINGUISTIC_FRAMING,
        l2_name="Humor/Sarcasm",
        l3_name="Snark framing",
        label="Snark framing",
        description="Uses snarky tone to delegitimize",
        examples=["In yet another genius move…"],
        default_severity=3,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"in (yet )?another (genius|brilliant|stunning) move",
            r"surprise,? surprise",
            r"who could have (seen|predicted)",
        ],
    ),
    # =========================================================================
    # E. STRUCTURAL & EDITORIAL MANIPULATION
    # =========================================================================
    # E.1 Headline Mismatch
    "E.1.1": ManipulationType(
        type_id="E.1.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Headline Mismatch",
        l3_name="Headline–body mismatch",
        label="Headline–body mismatch",
        description="Headline overstates/contradicts body content",
        examples=["Headline: 'Proven fraud' / body: 'unverified allegations'"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[],  # Requires cross-segment analysis
    ),
    "E.1.2": ManipulationType(
        type_id="E.1.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Headline Mismatch",
        l3_name="Timeframe mismatch",
        label="Timeframe mismatch",
        description="Headline implies current; story is old",
        examples=["Headline implies now; story is about 2019"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[],  # Requires cross-segment analysis
    ),
    # E.2 Information Burial
    "E.2.1": ManipulationType(
        type_id="E.2.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Information Burial",
        l3_name="Burying key facts",
        label="Burying key facts",
        description="Important information hidden deep in article",
        examples=["Correction in paragraph 18"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires structural analysis
    ),
    "E.2.2": ManipulationType(
        type_id="E.2.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Information Burial",
        l3_name="Inverted emphasis",
        label="Inverted emphasis",
        description="Minor details foregrounded; major context buried",
        examples=["Minor detail foregrounded; major context buried"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires structural analysis
    ),
    # E.3 Omission
    "E.3.1": ManipulationType(
        type_id="E.3.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Omission",
        l3_name="Omission bias (one-way updates)",
        label="Omission bias (one-way updates)",
        description="Reports negative but not subsequent positive",
        examples=["'Arrested' covered; 'charges dropped' ignored"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "E.3.2": ManipulationType(
        type_id="E.3.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Omission",
        l3_name="Missing baseline",
        label="Missing baseline",
        description="Reports change without baseline context",
        examples=["'Surge' without trendline"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"\b(surge|spike|jump|soar|plunge|crash)\b",
        ],
    ),
    # E.4 Quote Manipulation
    "E.4.1": ManipulationType(
        type_id="E.4.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Quote Manipulation",
        l3_name="Quote ordering bias",
        label="Quote ordering bias",
        description="Inflammatory quote first; clarifier buried",
        examples=["Inflammatory quote first; clarifier last"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires structural analysis
    ),
    "E.4.2": ManipulationType(
        type_id="E.4.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Quote Manipulation",
        l3_name="Quote mining",
        label="Quote mining",
        description="Removes qualifiers from quote",
        examples=["Removing qualifiers from a quote"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "E.4.3": ManipulationType(
        type_id="E.4.3",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Quote Manipulation",
        l3_name="Selective sourcing",
        label="Selective sourcing",
        description="Only quotes one side of debate",
        examples=["Only quoting advocates on one side"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    # E.5 Visual Manipulation
    "E.5.1": ManipulationType(
        type_id="E.5.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Visual Manipulation",
        l3_name="Thumbnail manipulation",
        label="Thumbnail manipulation",
        description="Worst video frame used as thumbnail",
        examples=["Worst video frame used as 'proof'"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires image analysis
    ),
    "E.5.2": ManipulationType(
        type_id="E.5.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Visual Manipulation",
        l3_name="Photo–text dissonance",
        label="Photo–text dissonance",
        description="Image doesn't match story content",
        examples=["Calm event shown with riot imagery"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires image analysis
    ),
    # E.6 Data Visualization Tricks
    "E.6.1": ManipulationType(
        type_id="E.6.1",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Data Viz Tricks",
        l3_name="Data-viz axis tricks",
        label="Data-viz axis tricks",
        description="Y-axis manipulation to exaggerate change",
        examples=["Y-axis starts at 95 to exaggerate change"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires image analysis
    ),
    "E.6.2": ManipulationType(
        type_id="E.6.2",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Data Viz Tricks",
        l3_name="Misleading scale/log",
        label="Misleading scale/log",
        description="Log scale used without explanation",
        examples=["Log scale used without explanation"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires image analysis
    ),
    "E.6.3": ManipulationType(
        type_id="E.6.3",
        category=ManipulationCategory.STRUCTURAL_EDITORIAL,
        l2_name="Data Viz Tricks",
        l3_name="Misleading map precision",
        label="Misleading map precision",
        description="Heatmap implies certainty where data sparse",
        examples=["Heatmap implies certainty where data sparse"],
        default_severity=3,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires image analysis
    ),
    # =========================================================================
    # F. INCENTIVE & META MANIPULATION
    # =========================================================================
    # F.1 Incentive Hiding
    "F.1.1": ManipulationType(
        type_id="F.1.1",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Incentive Opacity",
        l3_name="Incentive opacity",
        label="Incentive opacity",
        description="Source's funding/interests not disclosed",
        examples=["Think tank quoted without funding disclosure"],
        default_severity=4,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "F.1.2": ManipulationType(
        type_id="F.1.2",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Incentive Opacity",
        l3_name="Lobby laundering",
        label="Lobby laundering",
        description="Industry-backed content framed as neutral",
        examples=["Industry-backed study framed as neutral"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "F.1.3": ManipulationType(
        type_id="F.1.3",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Incentive Opacity",
        l3_name="Sponsored/native blur",
        label="Sponsored/native blur",
        description="Sponsored content disguised as editorial",
        examples=["'Partner content' written like reporting"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"partner content",
            r"sponsored (by|content)",
            r"paid (content|post|partnership)",
        ],
    ),
    "F.1.4": ManipulationType(
        type_id="F.1.4",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Incentive Opacity",
        l3_name="Commerce hijack",
        label="Commerce hijack",
        description="Product promotion disguised as news",
        examples=["'Best products to protect your family' as 'news'"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[
            r"best (products|deals|buys)",
            r"(top|must-have) picks",
            r"we (recommend|love|tried)",
        ],
    ),
    # F.2 Market Manipulation
    "F.2.1": ManipulationType(
        type_id="F.2.1",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Market Manipulation",
        l3_name="Market-moving fear framing",
        label="Market-moving fear framing",
        description="Fear headlines designed to move markets",
        examples=["'Panic' headlines that drive trading"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"market (panic|crash|collapse)",
            r"(investors|traders) (flee|panic|dump)",
            r"(stock|market) (bloodbath|carnage|rout)",
        ],
    ),
    # F.3 Agenda Masking
    "F.3.1": ManipulationType(
        type_id="F.3.1",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Agenda Masking",
        l3_name="Agenda masking",
        label="Agenda masking",
        description="Advocacy disguised as neutral reporting",
        examples=["Advocacy framed as neutral description"],
        default_severity=5,
        default_action=SpanAction.ANNOTATE,
        lexical_patterns=[],  # Requires semantic detection
    ),
    "F.3.2": ManipulationType(
        type_id="F.3.2",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Agenda Masking",
        l3_name="Call-to-action embedded",
        label="Call-to-action embedded",
        description="Call to action hidden in news article",
        examples=["'Tell lawmakers to vote now' inside reporting"],
        default_severity=5,
        default_action=SpanAction.REMOVE,
        lexical_patterns=[
            r"(call|contact|tell) (your )?(lawmakers?|representatives?|senators?)",
            r"sign (the|this) petition",
            r"take action (now|today)",
            r"(donate|contribute) (now|today)",
        ],
    ),
    # F.4 Normalization/Minimization
    "F.4.1": ManipulationType(
        type_id="F.4.1",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Normalization",
        l3_name="Normalization/minimization bias",
        label="Normalization/minimization bias",
        description="Downplays concerns without evidence",
        examples=["'Concerns are overblown' without evidence"],
        default_severity=4,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"concerns? (are|is) overblown",
            r"(nothing|no reason) to worry",
            r"blown out of proportion",
        ],
    ),
    "F.4.2": ManipulationType(
        type_id="F.4.2",
        category=ManipulationCategory.INCENTIVE_META,
        l2_name="Normalization",
        l3_name="Trivializing harm",
        label="Trivializing harm",
        description="Minimizes serious harm without justification",
        examples=["'Just a minor incident' (when serious)"],
        default_severity=5,
        default_action=SpanAction.REWRITE,
        lexical_patterns=[
            r"(just|only) a (minor|small|little)",
            r"not (that|so) (bad|serious|big)",
            r"could (have been|be) worse",
        ],
    ),
}


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def get_type(type_id: str) -> ManipulationType | None:
    """Get a manipulation type by its ID."""
    return MANIPULATION_TAXONOMY.get(type_id)


def get_types_by_category(category: ManipulationCategory) -> list[ManipulationType]:
    """Get all manipulation types in a category."""
    return [t for t in MANIPULATION_TAXONOMY.values() if t.category == category]


def get_types_by_severity(min_severity: int) -> list[ManipulationType]:
    """Get all manipulation types at or above a severity level."""
    return [t for t in MANIPULATION_TAXONOMY.values() if t.default_severity >= min_severity]


def get_types_with_patterns() -> list[ManipulationType]:
    """Get all manipulation types that have lexical patterns defined."""
    return [t for t in MANIPULATION_TAXONOMY.values() if t.lexical_patterns]


def get_all_type_ids() -> list[str]:
    """Get all type IDs in the taxonomy."""
    return list(MANIPULATION_TAXONOMY.keys())


def validate_type_id(type_id: str) -> bool:
    """Check if a type ID exists in the taxonomy."""
    return type_id in MANIPULATION_TAXONOMY


# -----------------------------------------------------------------------------
# Statistics
# -----------------------------------------------------------------------------

TAXONOMY_VERSION = "1.0"
TAXONOMY_DATE = "2026-01-24"
TOTAL_TYPES = len(MANIPULATION_TAXONOMY)

# Counts by category
COUNTS_BY_CATEGORY = {cat: len(get_types_by_category(cat)) for cat in ManipulationCategory}

# Counts by severity
COUNTS_BY_SEVERITY = {
    sev: len([t for t in MANIPULATION_TAXONOMY.values() if t.default_severity == sev]) for sev in range(1, 6)
}
