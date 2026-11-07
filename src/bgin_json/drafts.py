"""The zero-byte editor draft has no binary header or document name."""

EMPTY_DRAFT_WARNING = "Empty BGIN draft has no document name. Set a name before editing and create the first screen before compiling."


def empty_draft():
    return {"screens": []}


def draft_warnings(document):
    return [{"path": "/", "message": EMPTY_DRAFT_WARNING}] if document.get("screens") == [] and "name" not in document else []
