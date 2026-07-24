"""essays -- data-driven sports video-essay generation (channel-agent adapter).

Turns verified numbers from the data_explorer sports DBs into fully-scripted,
fact-checked, chart-illustrated video essays. First product: golf 54-hole
closer records ("video zero"), built on pga.betting.closer_rankings.

Stages: claims (source-lock) -> script (Opus, claim-locked) -> charts (SVG b-roll
with fail-closed face markers) -> [voice -> compose -> upload]. The design
principle throughout is the workspace one: no claim, and no image, reaches a
published frame without provenance.
"""
