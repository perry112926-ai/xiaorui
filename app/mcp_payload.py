"""Decode MCP content once; provider-specific success rules stay in adapters."""
import json
import re

class PayloadError(ValueError):
    pass


def extract_payload(result, *, envelope=None):
    """Require one unambiguous JSON value, optionally inside a text envelope.

    Structured content is authoritative if it satisfies the expected shape.
    No business success is inferred here; callers must verify their protocol.
    """
    structured = getattr(result, 'structuredContent', None)
    if structured is not None and (envelope is None or envelope(structured)):
        return structured
    values = []
    for block in result.content:
        if block.type != 'text':
            continue
        text = block.text
        if envelope is None:
            try:
                values.append(json.loads(text))
            except ValueError:
                continue
        else:
            decoder = json.JSONDecoder()
            for match in re.finditer(r'\{', text):
                try:
                    value, _ = decoder.raw_decode(text[match.start():])
                except ValueError:
                    continue
                if envelope(value):
                    values.append(value)
    if len(values) != 1:
        raise PayloadError('Expected exactly one MCP JSON payload')
    return values[0]
