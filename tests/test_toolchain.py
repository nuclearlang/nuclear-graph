"""The path of a planned piece comes from the platform's layout, not from the model's guess."""

import asyncio
import shutil

import pytest

from nuclear_graph.toolchain import Toolchain, layout_path, snake

LAYOUT = {
    "usecase": "components/{component}/domain/usecases/{file}.nuc",
    "appcomponent": "components/{component}/{component}_appcomponent.nuc",
    "statemanager": "components/{component}/presentation/{screen}/managers/{file}.nuc",
}


def test_snake_names_a_file():
    assert snake("BooksOfAuthor") == "books_of_author"
    assert snake("HTTPClient") == "http_client"
    assert snake("books") == "books"


def test_a_path_is_the_layout_with_the_names():
    assert layout_path(LAYOUT, "usecase", "BooksOfAuthor", "Books") == "components/books/domain/usecases/books_of_author.nuc"
    assert layout_path(LAYOUT, "appcomponent", "BooksAppComponent", "books") == "components/books/books_appcomponent.nuc"
    assert layout_path(LAYOUT, "statemanager", "BooksManager", "books", "list") == "components/books/presentation/list/managers/books_manager.nuc"
    assert layout_path(LAYOUT, "statemanager", "BooksManager", "books") == "components/books/presentation/widgets/managers/books_manager.nuc"
    assert layout_path(LAYOUT, "graph", "Planner", "ai") == ""


@pytest.mark.skipif(shutil.which("nuclear") is None, reason="nuclear is not installed")
def test_the_layout_comes_from_the_platform():
    layout = asyncio.run(Toolchain().layout("fastapi"))
    assert layout.get("controller") == "components/{component}/api/{file}.nuc", layout


def test_a_platform_is_named_as_a_platform():
    from nuclear_graph.toolchain import target
    assert target("backend") == ["--platform", "backend"]
    assert target("fastapi") == ["--dialect", "fastapi"]
