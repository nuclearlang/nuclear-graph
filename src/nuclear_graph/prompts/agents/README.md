# The prompts of the local agents

Each file is the whole prompt one step of a Nuclear Developer agent sends to its model. `{{name}}` is filled by the
agent (`Workbench.prompt` in nuclear-developer); a `## ` section whose body is left empty is dropped, so a prompt
never shows an empty heading. `{{guide}}` is the validated guide of the use case (`prompts/<use case>.md`).

| File | Agent · step | Model |
|---|---|---|
| `piece.md` | coder and tester · write | coder |
| `repair.md` | coder and tester · repair with the compiler's errors | coder |
| `faithful.md` | coder · the answer compiles but lacks a name, a path or a value the task writes | coder |
| `test.md` | tester · what it answers | coder |
| `analyze.md` | analyst · the resources a request in plain words describes (each line is then tried with the generator's dry run) | default |
| `plan.md` | planner · split the spec | default |
| `plan-again.md` | planner · the answer had no line in the form | default |
| `security.md` | security reviewer · review | default |
| `document.md` | documenter · write what the run did | default |
| `chat.md` | assistant · answer a message of the chat (over the `chat` guide) | default |
| `diagnose.md` | diagnoser · why a step failed and what to do (kind and action decided by rules) | default |

A change here is a change to an agent: run `eval/run.py local` in nuclear-developer and keep the report.
