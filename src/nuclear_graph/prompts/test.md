# Use case: tests

Write the tests of the code named in the spec, in Nuclear: one file `tests Name` with `@test("what it checks")`
methods, in `test/<name>_test.nuc`. Answer only with that file in one ```nuclear block. The tests may come before
the code: use exactly the names and signatures the task gives.

- One test per acceptance criterion: the normal case, the edge cases (empty, missing, repeated) and each error the
  use case can return (`status` 404, 409, 422).
- A test method returns `void`; get each instance with `inject<X>()` and call it with `~`; check with
  `expect(condition)`. A `Result` has `isOk`, `value` and `error` (`error.status`).
- The databases are in memory and start **empty** in every test: first create the rows the test reads (through the
  code that adds them, or `~repository.save(Entity(...))`), then check. An agent's model is `FakeModel(["answer"])`.
- Await a call once and keep its value (`found = ~books.byAuthor("Ada")`), then check `found.value`.
- Use only the declarations the task names. Never `inject<X>()` a class it does not list: when the task declares
  only models, build them and check their fields (`book = NewBook(title = "Dune")`, `expect(book.title == "Dune")`).
- A test that cannot pass because of a bug in the code is reported, never deleted or weakened.

The shape to copy (a backend; a mobile or web test uses the same words):

```nuclear
// The tests of authors.
tests Authors
  @test("adds an author and finds it by name")
  addsAndFinds() void
    authors = inject<AuthorsAppComponent>()
    made = ~authors.add(NewAuthor(name = "Ursula"))
    expect(made.isOk)
    found = ~authors.byName("Ursula")
    expect(found.value.name == "Ursula")

  @test("a missing author is not found")
  missing() void
    authors = inject<AuthorsAppComponent>()
    found = ~authors.byName("nobody")
    expect(found.error.status == 404)

  @test("a repeated name is a conflict")
  repeated() void
    authors = inject<AuthorsAppComponent>()
    ~authors.add(NewAuthor(name = "Octavia"))
    again = ~authors.add(NewAuthor(name = "Octavia"))
    expect(again.error.status == 409)
```
