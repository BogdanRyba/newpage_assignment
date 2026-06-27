"""Configuration constants for the notes service.

These module-level values tune search behaviour: how many results to return and which
common words to ignore when ranking. They are deliberately top-level so they can be
overridden in one place.
"""

MAX_RESULTS = 20

# Common words ignored when scoring a query against a note.
STOPWORDS = {"the", "a", "an", "to", "of", "and", "or", "is", "in", "on", "for"}
