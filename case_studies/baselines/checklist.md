# Baseline: Checklist

## Protocol
- Use the same evidence_packet.md and roots.yaml.
- For each root, mark each NEC slot as supported/unknown/unsupported.
- Select the root with the highest count of supported NEC slots.
- If no root has all NEC slots supported, select H_OTHER.

## Output
- predicted_root_id
- confidence: low/medium/high
- evidence_refs per NEC slot
