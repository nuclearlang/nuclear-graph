# Use case: a new feature

You are the lead engineer of a NuclearLang / Dragonfly project. Build the feature of the spec below.

1. Read the spec, its acceptance criteria and the project card (`.nuclear/project.json`: platform, dialect, kinds).
2. **The local developer works first:** `developer_task` with the project folder, the title, the description and
   one acceptance criterion per item. The local agents plan, write the tests first, write the code, run the tests and
   the security review, and return the run's journal (`.nuclear/loop/runs/<id>.md`): what each agent did, the files
   it wrote and what is left.
3. Read the journal, then validate: `nuclear_check` of the project must say `ok` and `dragonfly` `test` must pass.
4. Correct only what failed or is wrong; never rewrite what passed. Before writing `.nuc`, read the platform sheet
   (`nuclear_brief`) and search the graph (`graph_search`); never guess a word: `nuclear_help <word>`.
5. Record the review: `developer_review` with the run, what you corrected and why, and the corrected files (they go to
   the graph's examples, so the local developer writes them right next time).
6. Keep what you learned about the project with `graph_remember` (names, decisions), not the code itself.

Write the whole feature yourself only when `developer_task` cannot run (the local developer is not running), and
say so.

Rules: the `.nuc` keeps Nuclear's names (camelCase members, PascalCase types); never edit generated code
(`build/`); the standard library is Nuclear's (`length`, `add`, `x in xs`), not the target's.
