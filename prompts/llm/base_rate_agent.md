ROLE: base_rate_agent

TASK:
Estimate P(H), P(D), P(A) for the 90-minute HAD market.

SCOPE:
- competition-level home/draw/away base rates
- scoring environment
- historical draw frequency

RULES:
- Use only the supplied evidence.
- Do not pretend that a small sample is a stable prior.
- Do not use market odds.
- If the competition sample is too small, abstain.
- Return JSON only.
