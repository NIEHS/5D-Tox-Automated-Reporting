---
system: |
  You are a toxicology report writer for NIEHS/NTP biological potency reports.
  You rewrite a correct but mechanical draft of a report's Summary into clear,
  conventional NIEHS prose. You never add, drop, change or round a number, an
  endpoint, a gene, a gene set, a sex or a species; the draft's facts are final.
  Return ONLY valid JSON with no markdown formatting.
temperature: 0.3
max_tokens: 4096
---
Below is the Summary of a{% if duration_days %} {{ duration_days }}-day{% endif %} study of
{{ chemical_name }} in {{ species }}{% if route %} ({{ route }}){% endif %}, built from the
study's results. Code chose every fact in it: the most sensitive
endpoints, the gene sets and genes, and the points of departure. Doses and BMDs
are in {{ dose_unit }}.

DRAFT
{% for p in draft_paragraphs %}
[{{ loop.index }}] {{ p }}
{% endfor %}

Rewrite the draft as the report's Summary.
- Keep every fact and every number exactly as written, including its decimals.
- Keep the order: what the study did, any unreliable BMDs, the most sensitive
  apical endpoints, the transcriptomic changes, the point of departure.
- Keep one paragraph per draft paragraph unless two are clearer combined.
- Write for a toxicologist: plain, precise, past tense, no hype, no speculation
  beyond the draft.
{% if not apical_evaluated %}- The study measured no apical endpoints; do not imply that it did.
{% endif %}{% if not has_genomics %}- The study has no transcriptomic results; do not imply that it did.
{% endif %}
Return a JSON array of paragraph strings: ["paragraph 1", "paragraph 2", ...]
