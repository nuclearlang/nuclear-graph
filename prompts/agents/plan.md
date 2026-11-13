{{guide}}

## The platform

{{knowledge}}

## Spec

{{task}}

## Answer

Answer only the pieces, one per line, as:

    kind | Name | component | screen | what it declares

- `kind`: a kind of the layout above.
- `Name`: the declaration.
- `component`: one lowercase word, the feature's folder (books), never a path.
- `screen`: only for views, state managers and state models (list); otherwise `-`.
- `what it declares`: its fields or signatures and the names of other pieces it uses.

Every declaration the spec names is one piece, and nothing the spec does not ask for. Order them so each piece only
uses pieces before it.
