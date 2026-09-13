"""
AuditSure Layer 2 - Ontology Loader
=====================================
Single source of truth for reading facts out of the Layer 1 OWL ontology
(auditsure_gst_ontology.ttl) into plain Python data structures that the
rest of Layer 2 (Z3 constraint modules) and Layer 3 (LLM explainer) can
consume without ever touching rdflib/OWL syntax directly.

Design principle: business-type names, state names, threshold values,
and section citations all live ONLY in the ontology. This loader pulls
them out dynamically, so if the ontology is revised (e.g. GST Council
raises a threshold), Layer 2/3 pick up the change automatically without
a code edit or drift between the OWL model and the Python model.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

GST = Namespace("http://www.auditsure.in/ontology/gst#")


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "auditsure_gst_ontology.ttl"


def _local(uri: URIRef) -> str:
    """'http://.../gst#Section22' -> 'Section22'"""
    return str(uri).split("#")[-1]


def _lit(value) -> Optional[str]:
    return str(value) if value is not None else None


# ---------------------------------------------------------------------
#  Plain data structures returned to callers (no rdflib types leak out)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Threshold:
    id: str
    amount: float
    unit: str                      # "INR" | "PERCENT" | "YEARS" | "MONTHS"
    label: str
    citation: Optional[str] = None
    source_note: Optional[str] = None


@dataclass(frozen=True)
class LegalSection:
    id: str
    number: str
    title: str
    act: Optional[str] = None
    chapter: Optional[str] = None
    comment: Optional[str] = None
    threshold_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StateInfo:
    id: str
    label: str
    is_special_category: bool


@dataclass(frozen=True)
class OntologyClassInfo:
    id: str
    label: Optional[str]
    comment: Optional[str]
    citation: Optional[str]
    parent: Optional[str]


class OntologyLoader:
    """Loads auditsure_gst_ontology.ttl once and exposes typed accessors.

    Usage:
        onto = OntologyLoader()                 # uses bundled ttl
        onto.get_threshold("ThresholdRegistrationGeneral20L").amount
        onto.get_business_type_names()
        onto.get_section("22").title
    """

    def __init__(self, path: str | Path = DEFAULT_ONTOLOGY_PATH):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"Ontology file not found at {self.path}. "
                "Pass an explicit path to OntologyLoader(path=...)."
            )
        self.graph = Graph()
        self.graph.parse(str(self.path), format="turtle")

    # -- internal helpers --------------------------------------------

    def _label(self, uri: URIRef) -> Optional[str]:
        return _lit(self.graph.value(uri, RDFS.label))

    def _comment(self, uri: URIRef) -> Optional[str]:
        return _lit(self.graph.value(uri, RDFS.comment))

    def _citation(self, uri: URIRef) -> Optional[str]:
        return _lit(self.graph.value(uri, GST.legalCitation))

    def _subclasses_of(self, class_uri: URIRef) -> list[URIRef]:
        """Direct + transitive named subclasses of class_uri."""
        result: set[URIRef] = set()
        frontier = [class_uri]
        while frontier:
            current = frontier.pop()
            for child in self.graph.subjects(RDFS.subClassOf, current):
                if isinstance(child, URIRef) and child not in result:
                    result.add(child)
                    frontier.append(child)
        return sorted(result)

    # -- Thresholds -----------------------------------------------------

    @functools.lru_cache(maxsize=None)
    def get_all_thresholds(self) -> tuple[Threshold, ...]:
        out = []
        for t in self.graph.subjects(RDF.type, GST.Threshold):
            amount = self.graph.value(t, GST.thresholdAmount)
            unit = self.graph.value(t, GST.thresholdCurrency)
            note = self.graph.value(t, GST.sourceNote)
            out.append(Threshold(
                id=_local(t),
                amount=float(amount) if amount is not None else float("nan"),
                unit=_lit(unit) or "",
                label=self._label(t) or _local(t),
                citation=self._citation(t),
                source_note=_lit(note),
            ))
        return tuple(sorted(out, key=lambda x: x.id))

    def get_threshold(self, threshold_id: str) -> Threshold:
        for t in self.get_all_thresholds():
            if t.id == threshold_id:
                return t
        raise KeyError(f"No threshold individual named '{threshold_id}' in ontology.")

    def get_threshold_amount(self, threshold_id: str) -> float:
        """Convenience: just the number, for direct use as a Z3 constant."""
        return self.get_threshold(threshold_id).amount

    # -- Sections ---------------------------------------------------------

    @functools.lru_cache(maxsize=None)
    def get_all_sections(self) -> tuple[LegalSection, ...]:
        out = []
        for s in self.graph.subjects(RDF.type, GST.Section):
            number = self.graph.value(s, GST.sectionNumber)
            title = self.graph.value(s, GST.sectionTitle)
            chapter = self.graph.value(s, GST.partOfChapter)
            act = None
            if chapter is not None:
                act_uri = self.graph.value(chapter, GST.partOfAct)
                act = _local(act_uri) if act_uri else None
            thresholds = tuple(_local(t) for t in self.graph.objects(s, GST.hasThreshold))
            out.append(LegalSection(
                id=_local(s),
                number=_lit(number) or "",
                title=_lit(title) or "",
                act=act,
                chapter=_local(chapter) if chapter else None,
                comment=self._comment(s),
                threshold_ids=thresholds,
            ))
        return tuple(sorted(out, key=lambda x: (x.act or "", _section_sort_key(x.number))))

    def get_section(self, number: str, act: str = "CGSTAct2017") -> LegalSection:
        """Look up by bare section number, e.g. get_section('22')."""
        candidates = [s for s in self.get_all_sections() if s.number == number and (act is None or s.act == act)]
        if not candidates:
            raise KeyError(f"No Section '{number}' found for act='{act}'.")
        return candidates[0]

    def get_sections_with_thresholds(self) -> tuple[LegalSection, ...]:
        return tuple(s for s in self.get_all_sections() if s.threshold_ids)

    def get_thresholds_for(self, individual_local_name: str) -> tuple[Threshold, ...]:
        """Generic gst:hasThreshold lookup for ANY individual (Section,
        CompositionScheme, Rule, ...), not just Sections. e.g.
        get_thresholds_for('CompositionSchemeGoods') -> (1.5Cr, 75L thresholds)."""
        uri = GST[individual_local_name]
        ids = tuple(_local(t) for t in self.graph.objects(uri, GST.hasThreshold))
        return tuple(self.get_threshold(i) for i in ids)

    # -- States / Jurisdiction --------------------------------------------

    @functools.lru_cache(maxsize=None)
    def get_all_states(self) -> tuple[StateInfo, ...]:
        out = []
        for s in self.graph.subjects(RDF.type, GST.State):
            special = self.graph.value(s, GST.isSpecialCategory)
            out.append(StateInfo(
                id=_local(s),
                label=self._label(s) or _local(s),
                is_special_category=(str(special) == "true") if special is not None else False,
            ))
        return tuple(sorted(out, key=lambda x: x.id))

    def get_state_names(self) -> tuple[str, ...]:
        return tuple(s.id for s in self.get_all_states())

    def get_special_category_state_names(self) -> tuple[str, ...]:
        return tuple(s.id for s in self.get_all_states() if s.is_special_category)

    def is_special_category_state(self, state_id: str) -> bool:
        for s in self.get_all_states():
            if s.id == state_id:
                return s.is_special_category
        raise KeyError(f"Unknown state '{state_id}'.")

    # -- Generic class/individual introspection ----------------------------

    def get_subclass_names(self, class_local_name: str) -> tuple[str, ...]:
        """e.g. get_subclass_names('BusinessType') -> ('Manufacturer', 'Trader', ...)"""
        class_uri = GST[class_local_name]
        return tuple(_local(c) for c in self._subclasses_of(class_uri))

    def get_individuals_of_class(self, class_local_name: str) -> tuple[str, ...]:
        class_uri = GST[class_local_name]
        return tuple(sorted(_local(i) for i in self.graph.subjects(RDF.type, class_uri)))

    def get_business_type_names(self) -> tuple[str, ...]:
        return self.get_subclass_names("BusinessType")

    def get_supply_type_names(self) -> tuple[str, ...]:
        return self.get_subclass_names("Supply")

    def get_registration_status_names(self) -> tuple[str, ...]:
        return self.get_individuals_of_class("RegistrationStatus")

    def get_return_frequency_names(self) -> tuple[str, ...]:
        return self.get_individuals_of_class("ReturnFrequency")

    def get_class_info(self, class_local_name: str) -> OntologyClassInfo:
        uri = GST[class_local_name]
        parent = self.graph.value(uri, RDFS.subClassOf)
        return OntologyClassInfo(
            id=class_local_name,
            label=self._label(uri),
            comment=self._comment(uri),
            citation=self._citation(uri),
            parent=_local(parent) if isinstance(parent, URIRef) else None,
        )

    def get_version(self) -> str:
        """Reads the ontology's own owl:versionInfo, so callers (and
        ProofObject) never have to hardcode a version string that can
        silently drift out of sync with the actual loaded file."""
        for s in self.graph.subjects(RDF.type, OWL.Ontology):
            v = self.graph.value(s, OWL.versionInfo)
            if v is not None:
                return str(v)
        return "unknown"


def _section_sort_key(number: str):
    """Sorts '9', '10', '11A', '74A' in sane legal order (numeric, then letter suffix)."""
    digits = "".join(ch for ch in number if ch.isdigit())
    suffix = "".join(ch for ch in number if ch.isalpha())
    return (int(digits) if digits else 0, suffix)


# ---------------------------------------------------------------------
#  Module-level singleton convenience (most callers just want "the" ontology)
# ---------------------------------------------------------------------

_default_loader: Optional[OntologyLoader] = None


def get_default_loader() -> OntologyLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = OntologyLoader()
    return _default_loader
