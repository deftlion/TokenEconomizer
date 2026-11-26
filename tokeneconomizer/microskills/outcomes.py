"""Privacy-preserving proposer payload parsing and admission outcome summaries."""
import json
import re


def parse_payload_with_outcome(raw, parse_payload):
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
    exts, facts = parse_payload(raw)
    ext_drops = len(raw_exts) - len(exts) if isinstance(raw_exts, list) else 1
    fact_drops = len(raw_facts) - len(facts) if isinstance(raw_facts, list) else 1
    status = "processed" if exts or facts else "filtered" if ext_drops or fact_drops else "empty"
    return exts, facts, {"status": status, "extractors_filtered": ext_drops,
                        "facts_filtered": fact_drops}


def apply_proposal_outcome(raw, distiller, parse_payload, max_cands):
    """Parse `raw`, admit extractors/facts onto `distiller`, and return bounded outcome counts."""
    exts, facts, outcome = parse_payload_with_outcome(raw, parse_payload)
    if outcome["status"] == "processed":
        admitted = sum(distiller._admit_extractor(e) for e in exts)  # append-only
        # A forgotten id is refused at admission anyway: keep it from taking a slot.
        candidates = [f for f in facts if f.get("id") not in distiller.forgotten]
        reasons = {}
        for spec in candidates[:max_cands]:
            _, reason = distiller._admit(spec)
            code = reason.partition("(")[0]  # collapse grounding-fail(hit/minimum)
            reasons[code] = reasons.get(code, 0) + 1
        return {**outcome,
                "extractors_admitted": admitted,
                "extractors_rejected": len(exts) - admitted,
                "facts_forgotten": len(facts) - len(candidates),
                "facts_over_limit": max(0, len(candidates) - max_cands),
                "fact_outcomes": reasons}
    return outcome
