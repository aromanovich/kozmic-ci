"""
kozmic.utils
~~~~~~~~~~~~
"""
import json

from sqlalchemy import types


class JSONEncodedDict(types.TypeDecorator):
    """Represents an immutable structure as a JSON-encoded string."""
    impl = types.LargeBinary

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value
