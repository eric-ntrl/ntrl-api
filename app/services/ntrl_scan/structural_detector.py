# app/services/ntrl_scan/structural_detector.py
"""
Structural Detector: spaCy NLP-based manipulation detection (~80ms).

This detector uses linguistic analysis to find manipulation patterns that
require understanding sentence structure, not just keyword matching:
- Passive voice with hidden agent (D.3.1, D.3.2)
- Rhetorical questions (A.1.4)
- Agent deletion (D.3.2)
- Vague quantifiers and temporal markers (D.5.x)

Uses spaCy's en_core_web_sm model for fast, accurate parsing.
"""

import time
from functools import lru_cache

import spacy
from spacy.tokens import Doc, Span, Token

from app.taxonomy import get_type

from .types import (
    ArticleSegment,
    DetectionInstance,
    DetectorSource,
    ScanResult,
    SpanAction,
)


@lru_cache(maxsize=1)
def _get_spacy_model(model_name: str = "en_core_web_sm"):
    """Lazy-load and cache the spaCy model as a singleton.

    The model is only loaded on first call (~2-3s), and cached for
    all subsequent calls. Shared across StructuralDetector instances.
    """
    try:
        nlp = spacy.load(model_name)
    except OSError:
        import subprocess

        subprocess.run(["python", "-m", "spacy", "download", model_name])
        nlp = spacy.load(model_name)
    # Disable NER for speed — we only need parser and tagger
    nlp.select_pipes(disable=["ner"])
    return nlp


class StructuralDetector:
    """
    NLP-based detection for linguistic manipulation patterns.

    Uses spaCy to analyze sentence structure and identify manipulation
    that requires understanding grammar, not just keywords.
    """

    # Passive voice auxiliary verbs
    PASSIVE_AUX = {"was", "were", "been", "being", "is", "are", "be"}

    # Vague quantifier words (D.5.1)
    VAGUE_QUANTIFIERS = {
        "some",
        "many",
        "several",
        "few",
        "numerous",
        "various",
        "a number of",
        "a lot of",
        "plenty of",
        "most",
        "countless",
    }

    # Temporal vagueness markers (D.5.2)
    TEMPORAL_VAGUE = {
        "recently",
        "lately",
        "soon",
        "eventually",
        "shortly",
        "in recent years",
        "in recent months",
        "over the past",
        "in the coming",
        "before long",
    }

    # Absolutist words (D.5.4) - single tokens
    ABSOLUTES = {
        "everyone",
        "everybody",
        "nobody",
        "always",
        "never",
        "all",
        "none",
        "every",
        "any",
        "entirely",
        "completely",
        "absolutely",
        "totally",
        "utterly",
    }

    # Multi-word absolute phrases (D.5.4)
    ABSOLUTE_PHRASES = {"no one"}

    def __init__(self, model_name: str = "en_core_web_sm"):
        """Initialize with lazy-loaded spaCy model."""
        self.nlp = _get_spacy_model(model_name)

    def detect(
        self,
        text: str,
        segment: ArticleSegment = ArticleSegment.BODY,
    ) -> ScanResult:
        """
        Detect structural manipulation patterns in text.

        Args:
            text: The text to analyze
            segment: Which article segment this text is from

        Returns:
            ScanResult with detected manipulation instances
        """
        start_time = time.perf_counter()

        if not text or not text.strip():
            return ScanResult(
                spans=[],
                segment=segment,
                text_length=0,
                scan_duration_ms=0.0,
                detector_source=DetectorSource.STRUCTURAL,
            )

        # Parse with spaCy
        doc = self.nlp(text)

        detections: list[DetectionInstance] = []

        # Run all structural checks
        detections.extend(self._detect_passive_voice(doc, segment))
        detections.extend(self._detect_rhetorical_questions(doc, segment))
        detections.extend(self._detect_vague_quantifiers(doc, segment))
        detections.extend(self._detect_temporal_vagueness(doc, segment))
        detections.extend(self._detect_absolutes(doc, segment))

        # Sort by position
        detections.sort(key=lambda d: (d.span_start, d.span_end))

        scan_duration_ms = (time.perf_counter() - start_time) * 1000

        return ScanResult(
            spans=detections,
            segment=segment,
            text_length=len(text),
            scan_duration_ms=round(scan_duration_ms, 2),
            detector_source=DetectorSource.STRUCTURAL,
        )

    def _detect_passive_voice(self, doc: Doc, segment: ArticleSegment) -> list[DetectionInstance]:
        """
        Detect passive voice constructions that hide agency.

        Type D.3.1: Passive voice to hide agency
        Type D.3.2: Agent deletion
        """
        detections = []

        for sent in doc.sents:
            # Look for passive voice patterns
            passive_spans = self._find_passive_constructions(sent)

            for passive_span, has_agent in passive_spans:
                if has_agent:
                    # Passive with agent - less severe
                    type_id = "D.3.1"
                    severity = 2
                    rationale = "Passive voice construction (agent present)"
                else:
                    # Agentless passive - more severe
                    type_id = "D.3.2"
                    severity = 3
                    rationale = "Passive voice with hidden/deleted agent"

                manip_type = get_type(type_id)
                if manip_type:
                    detection = DetectionInstance(
                        type_id_primary=type_id,
                        segment=segment,
                        span_start=passive_span.start_char,
                        span_end=passive_span.end_char,
                        text=passive_span.text,
                        confidence=0.85,
                        severity=severity,
                        detector_source=DetectorSource.STRUCTURAL,
                        recommended_action=SpanAction.REWRITE,
                        rationale=rationale,
                    )
                    detections.append(detection)

        return detections

    def _find_passive_constructions(self, sent: Span) -> list[tuple[Span, bool]]:
        """
        Find passive voice constructions in a sentence.

        Returns list of (span, has_agent) tuples.
        """
        passives = []

        for token in sent:
            # Look for past participle with passive auxiliary
            if token.dep_ == "nsubjpass" or token.tag_ == "VBN":
                # Check if this is a passive construction
                has_aux = (
                    any(
                        child.dep_ == "auxpass" or (child.dep_ == "aux" and child.text.lower() in self.PASSIVE_AUX)
                        for child in token.head.children
                    )
                    if token.head
                    else False
                )

                # Also check the token itself if it's the head
                if token.tag_ == "VBN":
                    has_aux = has_aux or any(
                        child.dep_ == "auxpass" or (child.dep_ == "aux" and child.text.lower() in self.PASSIVE_AUX)
                        for child in token.children
                    )

                if has_aux or token.dep_ == "nsubjpass":
                    # Check for "by" phrase (agent)
                    has_agent = self._has_by_agent(token) or self._has_by_agent(token.head)

                    # Get the full passive phrase
                    passive_span = sent  # Use whole sentence for context
                    passives.append((passive_span, has_agent))
                    break  # One per sentence

        return passives

    def _has_by_agent(self, token: Token) -> bool:
        """Check if token has a 'by' prepositional phrase (agent)."""
        if token is None:
            return False

        for child in token.children:
            if child.dep_ == "agent" or (child.dep_ == "prep" and child.text.lower() == "by"):
                return True

        return False

    def _detect_rhetorical_questions(self, doc: Doc, segment: ArticleSegment) -> list[DetectionInstance]:
        """
        Detect rhetorical questions used as manipulation hooks.

        Type A.1.4: Rhetorical-question hook
        """
        detections = []

        for sent in doc.sents:
            text = sent.text.strip()

            # Must end with question mark
            if not text.endswith("?"):
                continue

            # Check if it's likely rhetorical
            if self._is_rhetorical_question(sent):
                manip_type = get_type("A.1.4")
                if manip_type:
                    detection = DetectionInstance(
                        type_id_primary="A.1.4",
                        segment=segment,
                        span_start=sent.start_char,
                        span_end=sent.end_char,
                        text=text,
                        confidence=0.75,  # Medium confidence - context dependent
                        severity=manip_type.default_severity,
                        detector_source=DetectorSource.STRUCTURAL,
                        recommended_action=SpanAction.REWRITE,
                        rationale="Rhetorical question used as engagement hook",
                    )
                    detections.append(detection)

        return detections

    def _is_rhetorical_question(self, sent: Span) -> bool:
        """
        Determine if a question is rhetorical (used for effect, not information).

        Heuristics:
        - Starts with "Is your", "Are you", "Could this", "What if"
        - Contains second person pronouns (you, your)
        - Contains modal verbs suggesting speculation
        """
        text_lower = sent.text.lower()

        # Common rhetorical question patterns
        rhetorical_starts = [
            "is your",
            "are you",
            "could this",
            "what if",
            "how can anyone",
            "how could anyone",
            "who would",
            "why would anyone",
            "isn't it",
            "don't you",
            "can you believe",
            "would you believe",
        ]

        for pattern in rhetorical_starts:
            if text_lower.startswith(pattern):
                return True

        # Check for second person + speculation
        has_second_person = any(token.text.lower() in {"you", "your", "yourself"} for token in sent)

        has_modal = any(
            token.tag_ == "MD" and token.text.lower() in {"could", "might", "would", "should"} for token in sent
        )

        return has_second_person and has_modal

    def _detect_vague_quantifiers(self, doc: Doc, segment: ArticleSegment) -> list[DetectionInstance]:
        """
        Detect vague quantifiers that lack specificity.

        Type D.5.1: Soft quantifiers
        """
        detections = []

        for token in doc:
            # Check single words
            if token.text.lower() in self.VAGUE_QUANTIFIERS:
                # Look for pattern like "some say", "many believe"
                if self._is_vague_attribution(token):
                    manip_type = get_type("D.5.1")
                    if manip_type:
                        detection = DetectionInstance(
                            type_id_primary="D.5.1",
                            segment=segment,
                            span_start=token.idx,
                            span_end=token.idx + len(token.text),
                            text=token.text,
                            confidence=0.70,
                            severity=2,  # Low severity
                            detector_source=DetectorSource.STRUCTURAL,
                            recommended_action=SpanAction.ANNOTATE,
                            rationale="Vague quantifier without specific attribution",
                        )
                        detections.append(detection)

        return detections

    def _is_vague_attribution(self, token: Token) -> bool:
        """Check if vague quantifier is used for attribution (e.g., 'some say')."""
        # Look for following verb that indicates attribution
        attribution_verbs = {"say", "believe", "think", "argue", "claim", "suggest"}

        # Check next tokens
        for i in range(1, 4):  # Look ahead up to 3 tokens
            if token.i + i < len(token.doc):
                next_token = token.doc[token.i + i]
                if next_token.lemma_.lower() in attribution_verbs:
                    return True

        return False

    def _detect_temporal_vagueness(self, doc: Doc, segment: ArticleSegment) -> list[DetectionInstance]:
        """
        Detect vague temporal references.

        Type D.5.2: Temporal vagueness
        """
        detections = []
        text_lower = doc.text.lower()

        for phrase in self.TEMPORAL_VAGUE:
            start = 0
            while True:
                idx = text_lower.find(phrase, start)
                if idx == -1:
                    break

                manip_type = get_type("D.5.2")
                if manip_type:
                    detection = DetectionInstance(
                        type_id_primary="D.5.2",
                        segment=segment,
                        span_start=idx,
                        span_end=idx + len(phrase),
                        text=doc.text[idx : idx + len(phrase)],
                        confidence=0.65,
                        severity=2,
                        detector_source=DetectorSource.STRUCTURAL,
                        recommended_action=SpanAction.ANNOTATE,
                        rationale="Vague temporal reference without specific date",
                    )
                    detections.append(detection)

                start = idx + len(phrase)

        return detections

    def _detect_absolutes(self, doc: Doc, segment: ArticleSegment) -> list[DetectionInstance]:
        """
        Detect absolute statements that are rarely accurate.

        Type D.5.4: Absolutes
        """
        detections = []

        # Check single-word absolutes
        for token in doc:
            if token.text.lower() in self.ABSOLUTES:
                # Check context - is this in a factual claim?
                if self._is_factual_claim_context(token):
                    manip_type = get_type("D.5.4")
                    if manip_type:
                        detection = DetectionInstance(
                            type_id_primary="D.5.4",
                            segment=segment,
                            span_start=token.idx,
                            span_end=token.idx + len(token.text),
                            text=token.text,
                            confidence=0.70,
                            severity=3,
                            detector_source=DetectorSource.STRUCTURAL,
                            recommended_action=SpanAction.REWRITE,
                            rationale="Absolute statement that may be inaccurate",
                        )
                        detections.append(detection)

        # Check multi-word absolute phrases
        text_lower = doc.text.lower()
        for phrase in self.ABSOLUTE_PHRASES:
            start = 0
            while True:
                idx = text_lower.find(phrase, start)
                if idx == -1:
                    break

                manip_type = get_type("D.5.4")
                if manip_type:
                    detection = DetectionInstance(
                        type_id_primary="D.5.4",
                        segment=segment,
                        span_start=idx,
                        span_end=idx + len(phrase),
                        text=doc.text[idx : idx + len(phrase)],
                        confidence=0.70,
                        severity=3,
                        detector_source=DetectorSource.STRUCTURAL,
                        recommended_action=SpanAction.REWRITE,
                        rationale="Absolute statement that may be inaccurate",
                    )
                    detections.append(detection)

                start = idx + len(phrase)

        return detections

    def _is_factual_claim_context(self, token: Token) -> bool:
        """Check if token is used in a factual claim context."""
        # Look for verbs of cognition/speech nearby
        claim_verbs = {"know", "believe", "think", "agree", "say", "claim"}

        # Check sentence
        sent = token.sent
        for t in sent:
            if t.lemma_.lower() in claim_verbs:
                return True

        return False

    def detect_title(self, title: str) -> ScanResult:
        """Convenience method to scan a title."""
        return self.detect(title, segment=ArticleSegment.TITLE)

    def detect_body(self, body: str) -> ScanResult:
        """Convenience method to scan body text."""
        return self.detect(body, segment=ArticleSegment.BODY)


@lru_cache(maxsize=1)
def get_structural_detector() -> StructuralDetector:
    """Get or create the singleton structural detector instance."""
    return StructuralDetector()
