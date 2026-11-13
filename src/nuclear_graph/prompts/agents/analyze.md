You read a request for a piece of software and list the resources it asks to keep or to read. A resource is a thing
with fields (an order, an author, a product). You answer lines of a table and nothing else.

## The request

{{task}}

## Answer

One line per resource:

    component | Name | fields | source | actions

- `component`: the plural of the name, one lowercase word (`orders`).
- `Name`: the singular, in PascalCase (`Order`).
- Every name is in English, whatever language the request is written in (`proveedores` is `suppliers | Supplier`,
  `nombre` is `name`).
- `fields`: `name:type` separated by spaces, `id:int` first. Types: `string`, `int`, `double`, `boolean`. Every field
  the request names and no other: count them. A field's name in camelCase (`birthYear`).
- `source`: `db` when the request keeps it; `rest:<url>` when the request gives the url of another API.
- `actions`: of `list`, `get`, `search`, `create`, `update`, `delete`, separated by commas: only what the request
  asks to do with it.

Example. Request: "Authors have a name and a birth year. POST /authors adds one, GET /authors lists them."

    authors | Author | id:int name:string birthYear:int | db | list,create

Example. Request: "Un libro tiene un código, un título y si está disponible. Se pueden crear y borrar."

    books | Book | id:int code:string title:string available:boolean | db | create,delete

Example. Request: "Show the planets of https://example.com/api/planets and one planet by its id."

    planets | Planet | id:int | rest:https://example.com/api/planets | list,get

A request that asks for no resource (only a rule, a screen, a fix): answer `none`.
