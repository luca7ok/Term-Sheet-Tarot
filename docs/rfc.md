# RFC Summary: Term Sheet Tarot


## 1. Problem definition

First-time founders often sign venture term sheets without grasping how clauses like participating preferences or full-ratchet anti-dilution actually shape their outcome. The underlying research question is whether an **archetypal, narrative reading helps non-experts understand and remember term-sheet risks better than a standard checklist.** The core engineering problem this creates: narrative framing is a known memory aid, but in a legal setting it is risky, because narratives invite invention. The challenge is building a narrative layer that cannot drift from the source text.

## 2. State of the art

| Approach | Pros | Cons |
| --- | --- | --- |
| Checklist-style term-sheet tools | Simple, factual, low risk of invention | Flat presentation; not shown to aid comprehension or recall |
| Regex / keyword rule parsing | Fully deterministic, no hallucination | Brittle on real-world clause wording; limited coverage |
| Zero-shot LLM prompting | Flexible, handles messy legal text | No grounding guarantee; prone to drift and hallucinated claims |
| Commercial API models (as reference only) | Strong raw extraction quality | Closed weights, not usable as the graded/deployed system |

Across these, the common gap is the same: tools that are safe (checklists, regex) don't engage memory the way narrative does, and tools that are narrative-capable (LLM prompting) aren't safe to ground in legal fact without extra machinery.

## 3. Proposal

**Term Sheet Tarot** turns a term sheet into a three-card tarot reading where every card is bound to a real clause, and its orientation encodes how founder-unfriendly that clause is.

What makes it different, and better:
- **Three jobs, never overlapping:** a fine-tuned SLM *reads* clauses into structured attributes, a deterministic rule engine *judges* risk, and a grounded composer *narrates* — checked by a verifier. The model never predicts what the rules already compute, so the narrative cannot drift from the source text the way plain zero-shot prompting can.
- **Deterministic card assignment:** which card, its rank and its orientation are a pure function of extracted clauses — never a model choice — so the system keeps narrative engagement without sacrificing the determinism of a rule-based approach.
- **Verified before narrated:** every reading passes a hallucination verifier (span + attribute checks) and policy guardrails before display; failures regenerate or fall back to a templated paragraph, never an unchecked narrative.
- **Directly tests the hypothesis:** a user study compares the tarot reading + risk table against the risk table alone, so the narrative layer's value is measured, not assumed.

Architectural diagrams and implementation detail are deliberately out of scope for this document; the purpose here is to fix the problem, survey what exists, and commit to a direction before moving to design.