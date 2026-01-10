# Evidence Packet Construction Protocol

## Purpose
Evidence packets represent what is knowable at freeze time T. They are *not* conclusions and must avoid hindsight framing.

## Permitted statement types
- Direct observations (what happened, where, when).
- Measurements (distances, timings, positions).
- Verbatim witness statements (tagged as reported).
- Procedural descriptions (what a standard procedure requires).
- Physical layout descriptions and contemporaneous environmental conditions.

## Prohibited statement types
- Causal attributions ("because", "led to", "resulted from", "therefore").
- Conclusions or analysis ("the investigation found", "report discusses").
- Post-event safety actions or recommendations.
- Meta-commentary about the report itself.
- Human-factors teaching text not tied to a specific observation.

## Section allowlist
Allowed sources by default:
- history
- synopsis (only if purely factual)

Disallowed sources by default:
- analysis
- conclusion
- safety actions

## Redaction rules
- Remove figure captions, footnotes, page numbers, and copyright lines.
- Drop lines containing explicit causal phrases or post-event actions.
- Merge broken sentences into single items; avoid mid-sentence splits.

## Evidence freeze (T)
- Freeze time is recorded in the evidence packet provenance section.
- Only information plausibly available at or before T is allowed.

## Worked example (before/after)
Before:
"The tug did not stop at the TRP and the aircraft struck the fence. The report discusses the importance of vigilance."

After:
"The tug continued moving beyond the TRP and the aircraft struck the fence."

## Inter-rater reliability target
- Two independent extractors should reach Cohen's kappa >= 0.70 on item inclusion decisions.
