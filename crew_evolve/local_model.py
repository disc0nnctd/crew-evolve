"""Optional, offline local model suggestions.

``LocalModel`` is a candidate generator.  It uses a cached
``sentence-transformers/all-MiniLM-L6-v2`` encoder to rank operator-approved
examples and never turns that ranking into an assignment or a policy change.
The model is opt-in through ``CREW_LOCAL_MODEL=minilm``.  Importing this
module does not import a model library or load model weights.

The scores in this module are retrieval similarities and heuristic gates.  They
are not probabilities of correctness.  Callers should display the returned
evidence and keep their existing validation and arithmetic checks in charge.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import workflows
from .model import ModelError


MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
MAX_APPROVED_EXAMPLES = 20

# These are deliberately conservative initial gates.  They are retrieval
# thresholds, not calibrated probabilities of correctness.
ROUTE_SIMILARITY_THRESHOLD = 0.44
ROUTE_MARGIN_THRESHOLD = 0.05
FIELD_SIMILARITY_THRESHOLD = 0.20
FIELD_MARGIN_THRESHOLD = 0.04

_LOCAL_SELECTIONS = frozenset({"minilm", "local", "all-minilm-l6-v2"})
_NEGATIVE_AVAILABILITY = frozenset({
    "cannot_work", "cant_work", "can_not_work", "can_t_work", "unavailable",
    "not_available", "inactive", "off_duty", "unavailable_flag",
})
_ACTIONS = frozenset({"coverage", "roster", "summary"})

_FIELD_DESCRIPTIONS = {
    "crew_id": "unique crew member identifier, badge, badge number, employee number, or staff ID",
    "name": "crew member person's full name, person, employee name",
    "base": "crew member home base, home station, station, or location",
    "role": "crew member role, rank, or position",
    "aircraft": "aircraft type, fleet, qualification, or aircraft model",
    "available": "positive availability flag: available, active, on call, can work, or can_work",
    "duty_id": "unique duty, rotation, or pairing identifier",
    "report_at": "duty report or start time",
    "release_at": "duty release or end time",
    "start_base": "duty origin or departure station",
    "end_base": "duty destination or arrival station",
    "required_roles": "roles or positions required by a duty",
}


def _normal(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _safe_text(value: object, limit: int = 160) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:limit]
    return ""


def _vectors(value: Any) -> list[list[float]]:
    """Convert common encoder output forms without importing numpy."""

    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise ModelError("Local model returned an invalid embedding.")
    if value and isinstance(value[0], (int, float)):
        value = [value]
    result: list[list[float]] = []
    width: int | None = None
    for row in value:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, (list, tuple)) or not row:
            raise ModelError("Local model returned an invalid embedding.")
        try:
            numbers = [float(item) for item in row]
        except (TypeError, ValueError):
            raise ModelError("Local model returned an invalid embedding.") from None
        if any(not math.isfinite(item) for item in numbers):
            raise ModelError("Local model returned a non-finite embedding.")
        if width is None:
            width = len(numbers)
        if len(numbers) != width:
            raise ModelError("Local model returned embeddings with different dimensions.")
        result.append(numbers)
    if not result:
        raise ModelError("Local model returned no embeddings.")
    return result


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ModelError("Local model returned embeddings with different dimensions.")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _as_list(value: object) -> list[str]:
    if isinstance(value, Mapping):
        values = list(value.keys())
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        values = list(value)
    else:
        values = []
    return list(dict.fromkeys(item for item in values if isinstance(item, str) and item.strip()))


class LocalModel:
    """A bounded local candidate generator with the remote model interface."""

    def __init__(self, *, encoder: object | None = None,
                 model_path: str | None = None,
                 model_name: str | None = None,
                 revision: str | None = None):
        self._selection = os.environ.get("CREW_LOCAL_MODEL", "").strip().casefold()
        self._encoder = encoder
        self._model_path = model_path or os.environ.get("CREW_LOCAL_MODEL_PATH", "").strip()
        configured_name = os.environ.get("CREW_LOCAL_MODEL_NAME", "").strip()
        self._model_name = model_name if model_name is not None else (configured_name or MODEL_ID)
        configured_revision = os.environ.get("CREW_LOCAL_MODEL_REVISION")
        if revision is not None:
            self._revision = revision
        elif configured_revision:
            self._revision = configured_revision.strip()
        elif self._model_path:
            # A directory has its own local revision; do not claim the pinned
            # hub revision for an arbitrary path.
            self._revision = ""
        else:
            self._revision = MODEL_REVISION
        self._load_attempted = encoder is not None
        self._encoder_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """Whether an explicit local selection (or test encoder) was supplied."""

        return self._encoder is not None or self._selection in _LOCAL_SELECTIONS

    @property
    def name(self) -> str:
        if self._model_path and self._model_name == MODEL_ID:
            return self._model_path
        if self._selection in _LOCAL_SELECTIONS and self._model_name == MODEL_ID:
            return "minilm"
        return self._model_name or "minilm"

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def model_id(self) -> str:
        return self._model_path or self._model_name

    def _require_selection(self) -> None:
        if self._encoder is not None:
            return
        if not self._selection:
            raise ModelError("No local model configured. Set CREW_LOCAL_MODEL=minilm to opt in.")
        if self._selection not in _LOCAL_SELECTIONS:
            raise ModelError(f"Unsupported local model {self._selection!r}. Set CREW_LOCAL_MODEL=minilm.")

    def _load_encoder(self) -> object:
        self._require_selection()
        if self._encoder is not None:
            return self._encoder
        with self._encoder_lock:
            # Another caller may have completed the initial load while this
            # caller was waiting.  The lock prevents a false second failure
            # from the one-shot _load_attempted guard.
            if self._encoder is not None:
                return self._encoder
            if self._load_attempted:
                raise ModelError("The configured local model could not be loaded.")
            self._load_attempted = True
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
            except (ImportError, ModuleNotFoundError):
                raise ModelError("Local model requires the optional sentence-transformers dependency.") from None
            model_name_or_path = self._model_path or self._model_name
            try:
                # local_files_only is intentional: this feature never downloads
                # weights and never contacts a model provider.
                self._encoder = SentenceTransformer(
                    model_name_or_path,
                    revision=None if self._model_path else self._revision,
                    local_files_only=True,
                )
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                detail = str(exc).strip().splitlines()[0] if str(exc).strip() else "model files are unavailable"
                raise ModelError(f"Could not load the cached local model with local_files_only=True: {detail}") from None
            return self._encoder

    @staticmethod
    def _encode(encoder: object, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encode = getattr(encoder, "encode", None)
        if not callable(encode):
            raise ModelError("Configured local model has no encode method.")
        try:
            encoded = encode(texts, convert_to_numpy=True, normalize_embeddings=False,
                             show_progress_bar=False)
        except TypeError:
            # Small injected encoders used for checks may implement only the
            # simple encode(texts) shape.  Real sentence-transformers uses the
            # bounded call above.
            encoded = encode(texts)
        vectors = _vectors(encoded)
        if len(vectors) != len(texts):
            raise ModelError("Local model returned the wrong number of embeddings.")
        return vectors

    def _evidence(self, *, started: float, operation: str, examples: int = 0,
                  candidates: list[dict] | None = None, **extra: object) -> dict:
        evidence: dict[str, object] = {
            "source": f"local {self.name} nearest approved examples",
            "operation": operation,
            "model": self.name,
            "model_id": self.model_id,
            "model_path": self._model_path or None,
            "revision": self._revision or None,
            "approved_example_count": examples,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "calibration": "heuristic retrieval gate, not probability of correctness",
            "local_files_only": True,
            "inference": False,
        }
        if candidates is not None:
            evidence["candidates"] = candidates
        evidence.update(extra)
        return evidence

    def _clarify(self, started: float, operation: str, reason: str,
                 question: str, *, examples: int = 0, **extra: object) -> dict:
        evidence = self._evidence(started=started, operation=operation, examples=examples,
                                 abstained=True, abstention_reason=reason, **extra)
        return {"action": "clarify", "question": question, "reason": reason,
                "evidence": evidence}

    @staticmethod
    def _approved_examples(context: Mapping[str, object]) -> list[dict[str, str]]:
        """Read only explicit examples, capped before any inference."""

        raw: list[object] = []
        for key in ("approved_examples", "approved_templates", "approved_workflows", "learned_workflows"):
            value = context.get(key)
            if isinstance(value, Mapping):
                raw.extend({"template": template, "action": action} for template, action in value.items())
            elif isinstance(value, (list, tuple)):
                raw.extend(value)
            if len(raw) >= MAX_APPROVED_EXAMPLES:
                break
        result: list[dict[str, str]] = []
        for item in raw[:MAX_APPROVED_EXAMPLES]:
            text: object = None
            action: object = None
            if isinstance(item, Mapping):
                if item.get("approved") is False:
                    continue
                text = item.get("text", item.get("question", item.get("template")))
                action = item.get("action")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                text, action = item
            if not isinstance(text, str) or not text.strip() or not isinstance(action, str) or action not in _ACTIONS:
                continue
            result.append({"text": text.strip()[:2000], "action": str(action)})
        return result[:MAX_APPROVED_EXAMPLES]

    @staticmethod
    def _context_targets(context: Mapping[str, object]) -> tuple[list[str], list[str]]:
        duties = context.get("duty_ids", context.get("duties", []))
        roles = context.get("roles", [])
        if isinstance(duties, Mapping):
            duty_values = list(duties.keys())
        elif isinstance(duties, Iterable) and not isinstance(duties, (str, bytes)):
            duty_values = []
            for item in duties:
                if isinstance(item, str):
                    duty_values.append(item)
                elif isinstance(item, Mapping) and isinstance(item.get("duty_id"), str):
                    duty_values.append(item["duty_id"])
        else:
            duty_values = []
        return _as_list(duty_values), _as_list(roles)

    def route(self, question: str, context: Mapping[str, object]) -> dict:
        started = time.perf_counter()
        self._require_selection()
        if not isinstance(context, Mapping):
            context = {}
        if not isinstance(question, str) or not question.strip():
            return self._clarify(started, "route", "empty request", "Please describe one read-only operation.")
        duties, roles = self._context_targets(context)
        guard = workflows.guard_request(question, duties, roles)
        examples = self._approved_examples(context)
        if guard is not None:
            return self._clarify(started, "route", str(guard.get("reason", "unsafe or incomplete request")),
                                 str(guard.get("reply", "Please clarify the read-only operation.")),
                                 examples=len(examples), extracted={"duties": [], "roles": []})
        if not examples:
            return self._clarify(started, "route", "no approved examples",
                                 "No approved workflow example supports this request. Please choose coverage, roster, or summary and review it manually.")
        signals = workflows._signals(question)
        positive_actions = [action_name for action_name, count in signals.items() if count]
        eligible = [index for index, example in enumerate(examples)
                    if not positive_actions or example["action"] in positive_actions]
        if not eligible:
            return self._clarify(started, "route", "no approved example for requested operation",
                                 "No approved example supports this operation. Please review it manually.",
                                 examples=len(examples))
        encoder = self._load_encoder()
        vectors = self._encode(encoder, [question] + [example["text"] for example in examples])
        scores = [_cosine(vectors[0], candidate) for candidate in vectors[1:]]
        # The guard has already established one positive operation. Restrict
        # the nearest-example comparison to approved examples for that
        # operation, while retaining the embedding as the candidate ranker.
        ranked = sorted(eligible, key=lambda index: (-scores[index], index))
        best_index = ranked[0]
        best_score = scores[best_index]
        second_score = scores[ranked[1]] if len(ranked) > 1 else -1.0
        candidate_evidence = [
            {"action": examples[index]["action"], "template": examples[index]["text"],
             "similarity": round(scores[index], 4)}
            for index in ranked[:3]
        ]
        if best_score < ROUTE_SIMILARITY_THRESHOLD:
            return self._clarify(started, "route", "similarity below heuristic threshold",
                                 "This request is outside the approved workflow examples. Please clarify the operation.",
                                 examples=len(examples), candidates=candidate_evidence,
                                 threshold=ROUTE_SIMILARITY_THRESHOLD, inference=True)
        if len(ranked) > 1 and best_score - second_score < ROUTE_MARGIN_THRESHOLD:
            return self._clarify(started, "route", "ambiguous nearest examples",
                                 "More than one approved workflow is plausible. Please specify coverage, roster, or summary.",
                                 examples=len(examples), candidates=candidate_evidence,
                                 threshold=ROUTE_SIMILARITY_THRESHOLD, margin_threshold=ROUTE_MARGIN_THRESHOLD,
                                 inference=True)
        action = examples[best_index]["action"]
        found_duties = workflows._extract_duties(question, duties)
        found_roles = workflows._extract_roles(question, roles)
        if action == "coverage" and (len(found_duties) != 1 or len(found_roles) != 1):
            return self._clarify(started, "route", "coverage requires exact known duty and role",
                                 "Specify one existing duty ID and one required role.", examples=len(examples),
                                 candidates=candidate_evidence,
                                 extracted={"duties": found_duties, "roles": found_roles}, inference=True)
        evidence = self._evidence(started=started, operation="route", examples=len(examples),
                                  candidates=candidate_evidence, selected_similarity=round(best_score, 4),
                                  inference=True,
                                  threshold=ROUTE_SIMILARITY_THRESHOLD,
                                  margin_threshold=ROUTE_MARGIN_THRESHOLD,
                                  extracted={"duties": found_duties, "roles": found_roles})
        result: dict[str, object] = {"action": action, "evidence": evidence,
                                     "provenance": {"source": "approved workflow example",
                                                    "template": examples[best_index]["text"],
                                                    "bounded": True}}
        if action == "coverage":
            result.update(duty_id=found_duties[0], role=found_roles[0])
        return result

    def mapping(self, pending: Mapping[str, object], fields: Sequence[str] | Mapping[str, object]) -> dict:
        started = time.perf_counter()
        self._require_selection()
        if not isinstance(pending, Mapping):
            raise ModelError("A pending import is required for local mapping.")
        headers = [item for item in pending.get("headers", []) if isinstance(item, str) and item.strip()]
        allowed_fields = _as_list(fields)
        if not headers or not allowed_fields:
            return self._clarify(started, "mapping", "missing columns or fields",
                                 "Provide source columns and allowed canonical fields for manual mapping.") | {"mapping": {}, "uncertainties": []}
        rows = pending.get("rows", [])
        rows = rows if isinstance(rows, list) else []
        source_texts: list[str] = []
        for header in headers:
            samples = []
            for row in rows[:3]:
                if isinstance(row, Mapping):
                    sample = _safe_text(row.get(header))
                    if sample:
                        samples.append(sample)
            source_texts.append(f"source column {header}; sample values: {' | '.join(samples)}")
        field_texts = [f"canonical field {field}: {_FIELD_DESCRIPTIONS.get(field, field)}" for field in allowed_fields]
        encoder = self._load_encoder()
        vectors = self._encode(encoder, source_texts + field_texts)
        source_vectors = vectors[:len(headers)]
        field_vectors = vectors[len(headers):]
        matrix = [[_cosine(source, field) for field in field_vectors] for source in source_vectors]
        best: dict[int, tuple[int, float]] = {}
        uncertainties: list[str] = []
        for source_index, scores in enumerate(matrix):
            ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
            winner = ranked[0]
            score = scores[winner]
            next_score = scores[ranked[1]] if len(ranked) > 1 else -1.0
            if score < FIELD_SIMILARITY_THRESHOLD or (len(ranked) > 1 and score - next_score < FIELD_MARGIN_THRESHOLD):
                uncertainties.append(f"Review '{headers[source_index]}': no clear canonical field match.")
                continue
            if allowed_fields[winner] == "available" and _normal(headers[source_index]) in _NEGATIVE_AVAILABILITY:
                uncertainties.append(f"Review '{headers[source_index]}': it expresses negative availability; declare an explicit inversion before mapping to available.")
                continue
            best[source_index] = (winner, score)
        # A canonical field may be selected by more than one source column.
        # Keep neither side when the winner is not clear.
        by_field: dict[int, list[tuple[int, float]]] = {}
        for source_index, (field_index, score) in best.items():
            by_field.setdefault(field_index, []).append((source_index, score))
        mapping: dict[str, str] = {}
        mapping_candidates: list[dict[str, object]] = []
        for field_index, choices in by_field.items():
            choices.sort(key=lambda item: (-item[1], item[0]))
            if len(choices) > 1 and choices[0][1] - choices[1][1] < FIELD_MARGIN_THRESHOLD:
                for source_index, _ in choices:
                    mapping_candidates.append({"source": headers[source_index], "field": allowed_fields[field_index], "similarity": round(dict(best)[source_index][1], 4), "status": "ambiguous"})
                    uncertainties.append(f"Review columns for '{allowed_fields[field_index]}': more than one source column is plausible.")
                continue
            source_index, score = choices[0]
            mapping[headers[source_index]] = allowed_fields[field_index]
            mapping_candidates.append({"source": headers[source_index], "field": allowed_fields[field_index], "similarity": round(score, 4), "status": "candidate"})
        evidence = self._evidence(started=started, operation="mapping", candidates=mapping_candidates,
                                  inference=True,
                                  threshold=FIELD_SIMILARITY_THRESHOLD, margin_threshold=FIELD_MARGIN_THRESHOLD)
        return {"mapping": mapping, "uncertainties": list(dict.fromkeys(uncertainties)), "evidence": evidence}

    def policy(self, request: str, current: Mapping[str, object]) -> dict:
        started = time.perf_counter()
        self._require_selection()
        return {
            "question": "Please provide the exact manual policy rule, jurisdiction, and values to apply. I will not infer safety limits or invent a rule.",
            "evidence": self._evidence(started=started, operation="policy", abstained=True,
                                       abstention_reason="manual policy rule required"),
        }


# Names that make integration and explicit configuration checks readable.
MiniLMModel = LocalModel
