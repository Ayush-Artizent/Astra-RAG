"""The one failure type the plane clients raise. Messages must be safe to show a caller."""


class PlaneError(Exception):
    """A plane refused the call or could not be reached."""
