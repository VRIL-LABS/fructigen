"""Turn a planned call into what a provider is actually sent.

Splitting never alters content: the blocks always concatenate back to the exact prompt. That is the
property that keeps a breakpoint a pure cost decision instead of a change to what the model reads.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

from .provider import Provider

Content = Union[str, list[dict[str, Any]]]


def message_content(texts: Sequence[str], marks: Sequence[int], provider: Provider) -> Content:
    """The user-message content for one call.

    ``texts`` are the rendered parts in order, each already carrying its trailing separator, and
    ``marks`` are the part indices a plan chose as breakpoints. A provider without explicit
    breakpoints, or a call with none, gets one plain string, so its request is byte-identical to one
    built without this library.

    Otherwise the parts are merged into one text block per breakpoint plus a final unmarked block.
    Merging keeps the block count low, which keeps every earlier breakpoint inside the provider's
    lookback window.
    """
    prompt = "".join(texts)
    valid = sorted({m for m in marks if 0 <= m < len(texts)})
    if not provider.explicit_breakpoints or not valid:
        return prompt
    if len(valid) > provider.max_breakpoints:
        raise ValueError(f"{len(valid)} breakpoints requested; {provider.name} allows "
                         f"{provider.max_breakpoints}")
    blocks: list[dict[str, Any]] = []
    start = 0
    for mark in valid:
        text = "".join(texts[start:mark + 1])
        if text:  # an empty block is rejected by the API and carries nothing to cache
            blocks.append({"type": "text", "text": text, "cache_control": {"type": "ephemeral"}})
        start = mark + 1
    tail = "".join(texts[start:])
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks if blocks else prompt
