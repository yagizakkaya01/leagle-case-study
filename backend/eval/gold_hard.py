"""Hard questions: few, each aimed at a failure mode reported for legal RAG systems.

Failure modes (see docs/EVAL.md for sources):
- superseded:     a later amendment replaces an earlier term ("inapplicable authority")
- precedence:     two provisions conflict and an order-of-precedence clause decides
- false_premise:  the question assumes something untrue (sycophancy)
- exception:      a rule with an exception / a right that only one party has (negation)
- multi_hop:      the answer needs facts from two pages and a calculation
- distractor:     look-alike numbers near the right one
- buried:         one sentence hidden in boilerplate (naive retrieval)
- party:          who may do what; easy to swap the parties (reasoning error)
- fabrication:    a plausible clause that does not exist (must say so)
- cross_lingual:  a Turkish question about an English amendment chain
"""
from __future__ import annotations

from eval.gold import CD, q

LA = "license_agreement"

GOLD_HARD = [
    q("hard-01", LA, "hard", "What is the current annual licence fee?", page=7,
      evidence="increased to 128,000 euros", must_contain=[["128,000", "128.000", "128000"]],
      failure_mode="superseded"),
    q("hard-02", LA, "hard", "How much notice does the licensee need to give today to "
      "terminate for convenience?", page=8, evidence="reduced to ninety days",
      must_contain=[["ninety", "90"]], failure_mode="superseded"),
    q("hard-03", LA, "hard", "Clause 2 says 250 named users but an amendment says 400. "
      "Which number applies, and why?", page=(1, 7, 8),
      evidence="Amendment prevails", must_contain=[["400"], ["amendment"]],
      failure_mode="precedence"),
    q("hard-04", CD, "hard", "Why did the court award the claimant 2.4 million pounds?",
      page=3, evidence="damages of 1.65 million pounds",
      must_contain=[["1.65"], ["not", "claimed", "sought", "rather", "instead", "only"]],
      failure_mode="false_premise"),
    q("hard-05", LA, "hard", "Can the licensor terminate the agreement for convenience?",
      page=6, evidence="may terminate only for a material breach",
      must_contain=[["no", "cannot", "can not", "not"], ["material breach"]],
      failure_mode="exception"),
    q("hard-06", LA, "hard", "Is the support fee included in the licence fee?", page=2,
      evidence="not part of the licence fee",
      must_contain=[["no", "not", "separately"], ["14,400", "14.400", "14400"]],
      failure_mode="exception"),
    q("hard-07", LA, "hard", "What is the licensor's maximum liability in a contract year "
      "under the current fee, in euros?", page=(6, 7),
      evidence="150 percent of the annual licence fee",
      must_contain=[["192,000", "192.000", "192000"]], failure_mode="multi_hop"),
    q("hard-08", LA, "hard", "How much does one additional named user cost per year?",
      page=2, evidence="380 euros per user per year", must_contain=[["380"]],
      failure_mode="distractor"),
    q("hard-09", LA, "hard", "How long must the licensee keep usage logs?", page=4,
      evidence="usage logs for at least eighteen months",
      must_contain=[["eighteen months", "18 months"]], failure_mode="buried"),
    q("hard-10", LA, "hard", "Which party can only terminate for an unremedied material "
      "breach, and how long is the remedy period?", page=6,
      evidence="remedied within forty-five days",
      must_contain=[["licensor", "quillstone"], ["forty-five", "45"]], failure_mode="party"),
    q("hard-11", LA, "hard", "Which country's law governs this licence agreement?",
      found=False, must_not=["laws of england", "dutch law governs", "governed by the laws"],
      failure_mode="fabrication"),
    q("hard-12", LA, "hard", "Ek protokollerden sonra lisans kaç kullanıcı ve hangi "
      "ülkeler için geçerli?", page=(7, 8), evidence="Luxembourg is added",
      must_contain=[["400"], ["luxembourg", "lüksemburg", "luksemburg"]],
      failure_mode="cross_lingual", tags=["cross_lingual"]),
]
