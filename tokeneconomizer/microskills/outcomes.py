"""Privacy-preserving proposer payload parsing and admission outcome summaries."""
import json
import re


def parse_payload_with_outcome(raw, detector_fields_ok):
    """Parse proposer JSON into `(extractors, facts, outcome)` without retaining raw text."""
    if not raw or (isinstance(raw, str) and not raw.strip()):
        return [], [], {"status": "no-reply"}
    # Preserve the existing brace-framed parser (e.g. for fenced replies).
    m = re.search(r"\{.*\}", raw, re.S) if isinstance(raw, str) else None
    try:
        obj = json.loads(m.group(0)) if m else None
    except (ValueError, RecursionError):
        obj = None
    if obj is None:
        try:
            json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            return [], [], {"status": "malformed-json"}
        return [], [], {"status": "non-object-json"}

    raw_exts, raw_facts = obj.get("extractors", []), obj.get("facts", [])
    exts = [e for e in (raw_exts if isinstance(raw_exts, list) else [])
            if isinstance(e, dict) and isinstance(e.get("name"), str) and e.get("name")
            and isinstance(e.get("pattern"), str) and e.get("pattern")]
    facts = [f for f in (raw_facts if isinstance(raw_facts, list) else [])
             if isinstance(f, dict) and isinstance(f.get("id"), str) and f.get("id")
             and isinstance(f.get("detector"), dict) and f.get("detector")
             and detector_fields_ok(f["detector"])
             and (f.get("cite") is None or isinstance(f.get("cite"), list))]
    ext_drops = len(raw_exts) - len(exts) if isinstance(raw_exts, list) else 1
    fact_drops = len(raw_facts) - len(facts) if isinstance(raw_facts, list) else 1
    status = "processed" if exts or facts else "filtered" if ext_drops or fact_drops else "empty"
    return exts, facts, {"status": status, "extractors_filtered": ext_drops,
                        "facts_filtered": fact_drops}


def apply_proposal_outcome(raw, distiller, detector_fields_ok, max_cands):
    """Parse `raw`, admit extractors/facts onto `distiller`, and return bounded outcome counts."""
    exts, facts, outcome = parse_payload_with_outcome(raw, detector_fields_ok)
    if outcome["status"] == "processed":
        admitted = sum(distiller._admit_extractor(e) for e in exts)  # append-only
        # A forgotten id is refused at admission anyway: keep it from taking a slot.
        candidates = [f for f in facts if f.get("id") not in distiller.forgotten]
        reasons = {}
        for spec in candidates[:max_cands]:
            _, reason = distiller._admit(spec)
            code = reason.partition("(")[0]  # collapse grounding-fail(hit/minimum)
            reasons[code] = reasons.get(code, 0) + 1
        outcome.update(extractors_admitted=admitted, extractors_rejected=len(exts) - admitted,
                       facts_forgotten=len(facts) - len(candidates),
                       facts_over_limit=max(0, len(candidates) - max_cands),
                       fact_outcomes=reasons)
    return outcome
