# Expanded local memory retrieval — Module 12.10

Exact FactParser and deterministic relation recall run first. Confirmed facts
override passive observations. Paraphrases are normalized by a small concept
lexicon (profession/employment/work, dish/meal/food, leisure/hobbies, and others),
then eligible evidence is ranked using sparse concept cosine similarity.
This is lightweight semantic matching, not an unrestricted language model.

SQLite selects at most 33 candidates per relation: 32 are inspected and the extra
row signals incomplete results. Queries exclude expired observations and unknown
named speakers. A 200 ms SQLite progress budget and 50 ms lock wait bound queries.
Selected observation re-reads and authoritative fact lookups also use a 50 ms
lock wait. Oversized legacy candidates are excluded in SQL before loading. Event
queries filter category in SQL so recent unrelated preferences cannot hide older
matching events. Locked confirmed facts produce an unavailable response, never
a lower-confidence passive fallback.
Multi-topic responses inspect at most three deterministic relations plus one
semantic branch, returning at most three ranked observations from that branch.
The response is capped at 1,800 characters.
The default ranking budget is 250 ms. Cancellation is checked between stages.
No embeddings, model download, cloud service, new dependency, or network request
is used. No semantic model installation is necessary. An unavailable ranker falls
back to the built-in concept ranker; unrecognized concepts produce an honest
unknown response rather than synthesized personal information.
Additional relation qualifiers are checked conservatively: a profession cannot
answer a work-address question, and an unrelated enjoyed sport cannot answer a
question about music or least-liked food.

The choice avoids an additional resident model on the 4 GB deployment target.
It sacrifices unrestricted paraphrase coverage for predictable latency and
transparent evidence selection. Injected rankers must themselves be synchronous
and bounded; the built-in ranker does no blocking I/O. Budgets cannot forcibly
terminate arbitrary third-party Python code.

Examples: “Which dish is my favorite?”, “What is my profession?”, “What do I do
for a living?”, “What do you remember about my work and hobbies?” Existing exact
favorite, birthplace, occupation and activity questions retain their responses.

Similarity alone never establishes truth. Personal observations are reconstructed
from complete assertion evidence using the existing grounding validator. Retrieval
also accepts verbatim past-tense event records such as “I went hiking last Sunday”;
this does **not** broaden automatic extraction. Capture time and typed passive ID
are retained in semantic responses. Weekday phrases remain phrases; no exact event
date is inferred. “Recent” does not prove an event date. Weekend matching requires
literal weekend/Saturday/Sunday evidence. Arbitrary time-range reasoning is unsupported.

Passive statements stay attributed to an unidentified speaker. Conflicting
single-valued relations are reported, never merged. Incomplete candidate sets
cannot establish a unique current value. Credentials and unsafe legacy assertions
are excluded. There is no memory-result cache; deletions and retention affect each
query. Deleting a confirmed fact preserves separately stored historical passive
observations, as described in PRIVACY.md. Review/correction/deletion semantics are
unchanged. Routine diagnostics contain no memory contents.

Physical voice and multi-hour reliability tests are separate from these SQLite
and mocked model tests. The multi-hour physical soak remains deferred.

Synthetic Windows benchmark: 100 queries over 303 temporary records, median
3.409 ms, p95 6.585 ms, maximum 9.551 ms. This is a small synthetic retrieval
measurement, not real voice latency or a very large database benchmark.
