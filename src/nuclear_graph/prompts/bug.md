# Use case: diagnose a bug

1. Reproduce it: write the smallest failing test (`tests` kind, `@test("...")`) that shows the bug, and run it.
2. Find the root cause in the `.nuc` (never in `build/`). Search the graph for the rule involved
   (`graph_search "<diagnostic code or behaviour>"`): many bugs are a target's habit (a TypeScript or Python name
   used in Nuclear).
3. Fix it once, in the shared code; grep every caller of what you change.
4. The new test and every old one pass; `nuclear_check` reports `ok`.
5. Explain in two lines: the cause and the fix.
