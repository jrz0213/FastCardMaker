"""Query results shared by all dictionary services."""

from ..utils import MapDict


class QueryResult(MapDict):
    def __init__(self, *args, **kwargs):
        super(QueryResult, self).__init__(*args, **kwargs)
        if self['result'] is None: self['result'] = ""
    def set_styles(self, **kwargs):
        for key, value in kwargs.items(): self[key] = value
    @classmethod
    def default(cls):
        return QueryResult(result="")
