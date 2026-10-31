"""Held-out questions for changed and cross-referenced provisions.

Written before the cross-reference fix and not used while building it, so they show
whether the fix generalises beyond the hard-set question that exposed the problem.
Two control questions ask about provisions that were NOT changed.
"""
from __future__ import annotations

from eval.gold import q

DA = "distribution_agreement"

GOLD_HELDOUT = [
    q("ho-01", DA, "heldout", "What is the minimum number of units the distributor must buy "
      "each quarter?", page=5, evidence="replaced by 350 units per Quarter",
      must_contain=[["350"]], failure_mode="superseded"),
    q("ho-02", DA, "heldout", "What is each party's liability cap?", page=5,
      evidence="replaced by 80,000 euros", must_contain=[["80,000", "80.000", "80000"]],
      failure_mode="superseded"),
    q("ho-03", DA, "heldout", "When must an invoice for an order placed in December be paid?",
      page=6, evidence="may be paid within 60 days", must_contain=[["60", "sixty"]],
      failure_mode="superseded"),
    q("ho-04", DA, "heldout", "The supplier raised the list price by 15 percent in the first "
      "year. Can the distributor terminate, and with how much notice?", page=4,
      evidence="raises the list price by more than ten percent",
      must_contain=[["yes", "can", "may"], ["thirty", "30"]], failure_mode="exception"),
    q("ho-05", DA, "heldout", "Without any price increase, can the distributor terminate in "
      "the first year?", page=(3, 4), evidence="may not terminate this Agreement",
      must_contain=[["no", "not", "cannot"]], failure_mode="exception"),
    q("ho-06", DA, "heldout", "Güncel sorumluluk üst sınırı ne kadar?", page=5,
      evidence="replaced by 80,000 euros", must_contain=[["80,000", "80.000", "80000"]],
      failure_mode="cross_lingual", tags=["cross_lingual"]),
    # controls: unchanged provisions must not be "updated" by the model
    q("ho-07", DA, "heldout", "What is the list price per unit?", page=2,
      evidence="list price is 240 euros per unit", must_contain=[["240"]],
      failure_mode="control"),
    q("ho-08", DA, "heldout", "In which countries is the distributor exclusive?", page=1,
      evidence="Austria and Switzerland", must_contain=[["Austria"], ["Switzerland"]],
      failure_mode="control"),
]
