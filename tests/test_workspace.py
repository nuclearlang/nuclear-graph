"""The lite toolbox of the agents: a project's files, read only, confined to the project."""

from nuclear_graph.workspace import Workspace


def project(tmp):
    files = {
        "config.nuc": 'dragonfly(platform = "backend", dialect = "fastapi")\n',
        "components/books/data/entities/book.nuc": '// A book of the library.\n@entity("books")\nentity Book()\n  @primary(generated = true)\n  id: int\n  title: string\n',
        "components/books/data/repositories/book_repository.nuc": 'repository BookRepository\n  byAuthor(author: string) Book[]\n    where({ "author": author })\n    getMany()\n',
        "build/app/x.nuc": "Generated\n",
    }
    for rel, text in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text)
    return Workspace(str(tmp))


def test_an_agent_reads_only_the_project(tmp_path):
    ws = project(tmp_path)
    assert ws.read("components/books/data/entities/book.nuc", 3, 2) == "   3  entity Book()\n   4    @primary(generated = true)\n… 2 more lines (read from line 5)"
    assert ws.read("../outside.txt").startswith("not read: ../outside.txt is outside the project")
    assert ws.read("build/app/x.nuc").startswith("not read: build/app/x.nuc is generated or hidden")
    assert ws.list() == "components/\nconfig.nuc" and ws.list("components/books") == "data/"
    assert ws.find("**/*_repository.nuc") == "components/books/data/repositories/book_repository.nuc"
    assert ws.grep("byAuthor") == "components/books/data/repositories/book_repository.nuc:2: byAuthor(author: string) Book[]"
    assert ws.grep("nothing like it") == "(no line has it)"


def test_the_context_of_a_task_is_the_files_that_declare_its_names(tmp_path):
    ws = project(tmp_path)
    assert ws.declarations() == {"Book": "components/books/data/entities/book.nuc", "BookRepository": "components/books/data/repositories/book_repository.nuc"}
    context = ws.context("A use case BooksOfAuthor(books: BookRepository) whose exec returns Book[] in a Result.")
    assert context.index("// components/books/data/repositories/book_repository.nuc") < context.index("// components/books/data/entities/book.nuc")
    assert "byAuthor(author: string) Book[]" in context and "Generated" not in context
    assert "book_repository" not in ws.context("BookRepository and Book", skip="components/books/data/repositories/book_repository.nuc")
    assert ws.outline("components/books/data/repositories/book_repository.nuc") == "repository BookRepository\n  byAuthor(author: string) Book[]"


def test_a_rename_is_every_file_that_writes_the_name_with_the_new_one(tmp_path):
    files = {
        "components/books/domain/models/book.nuc": "Book\n  title: string\n",
        "components/books/domain/usecases/all_books.nuc": "usecase AllBooks(books: BookRepository)\n  exec() Result<Error, Book[]>\n    ~books.all()\n",
        "components/books/domain/models/author.nuc": "Author\n  name: string\n",
        "components/books/domain/models/new_book.nuc": "NewBook\n  title: string\n",
        "components/books/domain/usecases/list_books.nuc": "usecase ListBooks(books: BookRepository)\n  exec() Result<Error, NewBook>\n    ~books.first()\n",
        "build/app/book.nuc": "Book\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    ws = Workspace(str(tmp_path))
    # the names of the project built from it follow it (a framework binds a repository to its entity by its name);
    # a plural is another word, and so is a name the project does not declare
    assert ws.renames("Book", "Title") == {"Book": "Title", "NewBook": "NewTitle"}
    out = ws.renamed("Book", "Title")
    # generated folders are not read
    assert out == {
        "components/books/domain/models/book.nuc": "Title\n  title: string\n",
        "components/books/domain/models/new_book.nuc": "NewTitle\n  title: string\n",
        "components/books/domain/usecases/all_books.nuc": "usecase AllBooks(books: BookRepository)\n  exec() Result<Error, Title[]>\n    ~books.all()\n",
        "components/books/domain/usecases/list_books.nuc": "usecase ListBooks(books: BookRepository)\n  exec() Result<Error, NewTitle>\n    ~books.first()\n",
    }
    assert (tmp_path / "components/books/domain/models/book.nuc").read_text() == "Book\n  title: string\n"

