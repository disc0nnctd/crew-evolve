# Bounded workflow reuse

`crew_evolve.workflows` reuses reviewed read-only workflow examples without a
network request, model call, data mutation, or generated code. It is a small
route layer for the application; the operations engine still produces every
coverage, roster, and summary result.

## Call sequence

The application should call `guard_request(question, duty_ids, roles)` first.
It returns a clarification plan when the request is unsafe, incomplete,
unknown, contradictory, or asks for more than one target. A `None` result
means that the request is structurally safe to consider. The application can
then call:

```python
plan = route(question, duty_ids, roles, learned_workflows)
if plan is None:
    # Use the separate provider proposal path or show a clarification.
    ...
```

`route` only reuses actions present in the reviewed
`{template: action}` mapping stored by learning. Supported actions are
`coverage`, `roster`, and `summary`. Coverage plans contain one exact
`duty_id` and one canonical role. Duty identifiers are matched as complete
tokens, so `D-10` cannot be selected from `D-100`. `first_officer`, `first
officer`, and `first-officer` resolve to the supplied canonical role.

`workflow_key(question, duty_ids, roles)` is the compatibility helper for
learning and teaching. It returns `(canonical_template, found_duty_ids,
found_roles)` in the same shape as the older learning helper, while using the
same exact token extraction as routing.

The plan carries `provenance` and `candidates`. The same evidence is available
without selecting a plan through `candidates(...)` and `provenance(...)`; this
lets the interface show which approved example supported a reuse or why the
router abstained.

For a plain learned mapping, route scans at most 128 workflow entries and
retains at most 16 matching candidates. Entries beyond the scan bound produce
an abstention when they are needed for a route; candidate and provenance
inspection reports the truncation. Role spellings are indexed by their first
word and the request is scanned once, so a workspace with many distinct roles
does not create one regular expression per role.

## Guard behavior

Writes such as assigning, removing, changing a base, or changing policy are
always clarified. A negated write can still permit a read: “Don't assign
anyone; just show eligible captain candidates for D-100” routes to coverage.
The positive write in “Don't show candidates; assign Noor to D-100 as captain”
is clarified.

The guard also clarifies missing or unknown duty and role targets, multiple
duties or roles, and mixed operations. Summary and roster requests can use
explicit negation to disambiguate scope, for example “aggregate counts, not a
duty-by-duty list” and the reverse. Prompt-like instructions are treated as
untrusted text and never influence routing.

Reuse stays conservative: no approved example means no automatic route, and
unclear or conflicting candidates return `None`. The caller remains responsible
for running the returned read-only plan through `App.execute` and for using a
separate provider path when a new phrase needs review.
