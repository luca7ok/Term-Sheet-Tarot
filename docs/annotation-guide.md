# Annotation guide v1

Guide version `g1-guide-v1`. This version is tied to the G1 dataset version, per section 3.1 of the architecture doc.

## Purpose

You label clauses in preferred-stock charters and voting agreements. The labels become G1, the gold set that scores the extractor in Week 9. Every label must be a valid instance of the ontology. A label is a character span, a clause type, and the attributes for that type.

## The five clause types

Fill every attribute listed for the type. The tool rejects impossible combinations on export.

**liquidation_preference.** What each series receives first when the company is liquidated or sold.

- `multiple`. The preference as a multiple of the original price. A number above 0. "Original price plus declared dividends" is 1.
- `participating`. True if holders also share in the remainder with common. False if they take the preference or convert, whichever is more.
- `cap`. Total return cap as a multiple. Fill it only when `participating` is true. Leave it empty for no cap.
- `seniority`. `senior`, `pari_passu` or `junior`, relative to the other preferred series.

**anti_dilution.** How the conversion price falls after a cheaper issuance.

- `method`. `broad_based_weighted_average`, `narrow_based_weighted_average`, `full_ratchet` or `none`. Broad-based counts all common stock, options and convertibles in the denominator. Narrow-based counts less. Choose `none` when the charter says no adjustment applies.
- `pay_to_play`. True if holders lose protection or convert when they skip a follow-on round.

**board_composition.** Who may elect directors.

- `investor_seats`. Seats elected by preferred holders, alone or as a series.
- `common_seats`. Seats elected by common holders alone.
- `independent_seats`. Seats elected by preferred and common voting together, or seats the text requires to be independent.
- The three counts must sum to at least 1. Count what the charter fixes. Do not count seats that the bylaws set later.

**drag_along.** A right to force other holders to sell in a sale of the company.

- `trigger_holders`. Pick every group whose approval triggers the drag. `board`, `preferred_majority`, `common_majority`. At least one.
- `founder_carve_outs`. True if founders or common holders get different terms or an exemption.

**protective_provisions.** Matters that need preferred holders' consent.

- `veto_matters`. Pick every matter listed. `amend_charter`, `new_senior_security`, `change_board_size`, `dividends`, `liquidation_or_sale`, `debt_above_threshold`, `redemption`.
- `voting_threshold`. `majority` or `supermajority`. A supermajority is any threshold above 50 percent of the series.

Mark a matter in `veto_matters` only if the text lists it. Do not infer matters from the NVCA model.

## Span rules

1. One region per clause per series. If three series each carry a liquidation preference, make three regions.
2. Include the whole operative clause, from its first operative word to its last. Include its sub-paragraphs and provisos.
3. Exclude the heading and the section number.
4. A clause may cite a defined term, for example a "Deemed Liquidation Event". Label only the clause. Look up the definition separately and use it to fill the attributes. Do not label the definition.
5. Nested sub-clauses belong to the parent clause. Do not label them as their own regions.
6. Regions of the same type must not overlap. Regions of different types should not overlap. If they must, kappa counts the earlier start only.
7. Start and end on word boundaries. A few stray punctuation characters at the edges are fine.

## What counts as "none"

Unlabelled text is "none". These stay unlabelled.

- Definitions, recitals, headings and tables of contents.
- Dividends, redemption mechanics, conversion mechanics and general voting rights.
- Clauses of the five types in a document that is not a charter or voting agreement, such as a cover page.
- Cross-references that do not state the term, for example "as provided in Section 3".

If a clause only restates another clause, label the original and leave the restatement.

## Multiple series

Make one region per series. Fill the attributes from that series. If the text covers several series at once, make one region and say so in a comment on the region. Series A, B and C often differ in seniority, so check each.

## NVCA pointers

Use the NVCA model documents as a reference for what a clause usually contains. Do not copy their text. Read these sections.

- Model Certificate of Incorporation, the section on liquidation, dissolution or winding up, including the part on deemed liquidation events.
- Model Certificate of Incorporation, the section on voting, which covers both the election of directors and the protective provisions.
- Model Certificate of Incorporation, the section on adjustments to the conversion price for diluting issues.
- Model Voting Agreement, the sections on board composition and on the drag-along.

The drag-along usually lives in the voting agreement, not the charter. A charter may have none.

## Install and open Label Studio

1. Run `docker compose up -d label-studio` from the repo root.
2. Open http://localhost:8080.
3. On first run, sign up with a local account. Use any address you like. Data stays in `.label_studio/` on your machine, which git ignores.
4. Each annotator needs a separate project, so nobody sees the other's labels. Create a project named `g1-pilot-<yourname>`.
5. Open Labeling Setup, choose Custom template, and paste `data/golden/g1_extraction/label_config.xml`.
6. Generate the task file. Charters from the crawl live in `data/raw/edgar-v2`.

   ```
   uv run python -m tarot.golden.labelstudio data/raw/edgar-v2 \
     data/golden/g1_extraction/pilot.txt > data/interim/pilot_tasks.json
   ```

7. In the project, click Import and upload `pilot_tasks.json`.
8. Select a clause label, drag over the text, then fill the attribute fields in the region panel. Only the fields for that type show.
9. Submit each task when done.
10. Export from the Data Manager as JSON (the full format, not JSON-MIN).

To check an export, run `uv run python -m tarot.golden.kappa a.json b.json`. To check one annotator's labels, load it with `tarot.golden.labelstudio.from_export`. It raises with the region id and the reason for each invalid region.

## Pilot protocol

1. Both annotators label the same 5 filings in `pilot.txt`. No pre-labels.
2. Work alone. Do not discuss labels, attributes or edge cases until both have exported.
3. Export both projects and run the kappa script.
4. If overall kappa is at least 0.7, the guide stands. Adjudicate disagreements, then move to the other 25 filings.
5. If it is below 0.7, read the per-type scores and the disagreeing regions together. Revise this guide, bump the version, and relabel a fresh set of 5 filings.

## Worked examples

The examples come from the first crawl in `data/raw/edgar`, not from the pilot set. Quotes are short on purpose. Read the full clause in the filing.

**Example 1, liquidation preference.** Document `edgar-0001193125-04-213821-dex31a` (Targacept). Section 2(a)(i) begins "In the event of any liquidation, dissolution or winding up of the affairs of the corporation...". It pays Series C "an amount equal to the greater of (A) the Series C Original Price... plus the accrued but unpaid Series C Dividend" before Series B, Series A or Common. Label the whole of 2(a) for Series C as one region. Exclude the "2. Liquidation." heading. The sub-paragraph that treats a Fundamental Transaction as a liquidation event belongs to the parent clause. The term "Series C Original Price" is defined in Section 4(a)(iii). Look it up to set `multiple`. Series C is paid before Series B and A, so `seniority` is `senior`. Series B and Series A get their own regions.

**Example 2, board composition.** Document `edgar-0001193125-07-204564-dex35` (MAP Pharma). Section B(6)(c), "Board of Directors Election", gives one director to common, one to Series A, three to Series B and one to Series C. The rest are elected by all holders together. Label items (ii) to (vi) as one region. Exclude the heading and item (i), which defers the board size to the bylaws. `investor_seats` is 5, `common_seats` is 1. The remaining seats are elected jointly, but the charter does not fix how many there are, so `independent_seats` is 0. Count only seats whose number the charter states, so the sum is 6. Item (vii) changes the rule after a qualified IPO. Keep it inside the region, since it is a nested proviso.

**Example 3, protective provisions across series.** Document `edgar-0001193125-04-213821-dex31a` (Targacept). Section 3 has separate covenants for each series, for example "Series A Preferred Protective Covenants" in 3(b) and "Series B Preferred Protective Covenants" in 3(c). Each begins "the corporation shall not, directly or indirectly, take any of the following actions without first obtaining the affirmative vote...". Make one region per series covenant, so 3(b), 3(c), 3(d) and 3(e) are four regions. Fill `veto_matters` from the items listed under each one. Section 3(e) also limits the board to nine members. Tick `change_board_size` there. Leave the board limit out of any board_composition label, since it sets no seats.
