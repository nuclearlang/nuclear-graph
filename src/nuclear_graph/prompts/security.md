# Use case: security review

Review the change named in the spec for security problems, from the most to the least severe.

Check: input validated at every trust boundary (model rule decorators: `@minLength`, `@email`, `@url`, ranges);
authorization (`@acl`, guards) on every route that reads or changes data of a user; no secret in code (use
`env("VAR")`); SQL built only through the repository's query builder; file paths from users never joined without
checking; errors that do not leak internals; dependencies added in `config.nuc` that are known and pinned.

For each finding: file:line, the problem, a concrete attack, the fix in Nuclear. No finding is "maybe": either
show the input that breaks it or leave it out.
