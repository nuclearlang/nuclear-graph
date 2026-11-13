A step of the NuclearLang pipeline failed. Explain to the developer why, in plain English, and what to do next.

## The step

{{step}}

## The failure (the end of its output)

```
{{failure}}
```

## What the tools found

{{evidence}}

## What is known about it

{{known}}

## Already decided

- Kind of failure: `{{kind}}`
- What to do: {{action}}

## Answer

Three short parts, without headings:

1. The cause, in one or two sentences, naming the file, line or service when the failure shows it.
2. The evidence: the one line of the failure or of the tools that proves it.
3. The next step, concrete (a command, a file to change, a sentence to add to the spec).

Use only what the failure and the tools show; never invent a file, an error or a command. Speak of the project's
`.nuc` files and their Nuclear names only: never of the generated code (Python, TypeScript, Dart), its files or its
imports — the developer never edits it.
