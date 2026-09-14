"""Session-scoped progressive disclosure of already selected optional tools.

This owner prepares schemas and validates discovery requests. It never expands
permissions, loads plugins, fetches schemas, or executes a tool.
"""

from __future__ import annotations

import copy
import functools
import math
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .catalogs.core import _CORE_TOOLS

BRIDGE_NAMES = frozenset({"tool_search", "tool_describe", "tool_call"})
_STOP_WORDS = frozenset(
    "a an and are as at be by can do for from have how i in is it me my of on or please that the there this to tool tools use want which with".split()
)


_stemmers = threading.local()


@functools.lru_cache(maxsize=4096)
def _stem(word: str) -> str:
    # Snowball carries mutable parser state. Each execution thread owns its
    # instance; only immutable stem strings enter the shared bounded cache.
    import snowballstemmer

    if getattr(_stemmers, "english", None) is None:
        _stemmers.english = snowballstemmer.stemmer("english")
    return _stemmers.english.stemWord(word)


def _terms(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())
    return [_stem(word) for word in words if word not in _STOP_WORDS]


def _strings(value: object, *, maximum: int, label: str) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise ValueError(f"{label} requires 1–{maximum} nonempty strings")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 1000
        for item in values
    ):
        raise ValueError(f"{label} requires bounded nonempty strings")
    return list(dict.fromkeys(cast(str, item).strip() for item in values))


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


@dataclass(frozen=True)
class ToolCatalog:
    """A copied selection snapshot; rebuild when preparing or handling a call."""

    direct: tuple[dict[str, Any], ...]
    optional: Mapping[str, dict[str, Any]]

    @classmethod
    def selected(
        cls, tools: Sequence[dict[str, Any]], direct_names: Sequence[str] = ()
    ) -> ToolCatalog:
        direct = []
        optional = {}
        protected = set(_CORE_TOOLS) | set(direct_names) | {"clarify"}
        seen = set()
        for definition in tools:
            function = definition.get("function", {})
            if not isinstance(function, dict):
                raise ValueError("Selected tool has an invalid function schema")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("Selected tool is missing its function name")
            if name in seen or name in BRIDGE_NAMES:
                raise ValueError(
                    "Selected tools contain duplicate or reserved discovery names"
                )
            seen.add(name)
            entry = copy.deepcopy(definition)
            if name in protected or name.startswith(("forecast", "calibration_")):
                direct.append(entry)
            else:
                optional[name] = entry
        return cls(tuple(direct), optional)

    def wire_tools(self, *, listing_chars: int = 8000) -> list[dict[str, Any]]:
        if not self.optional:
            return list(self.direct)
        listing = []
        remaining = max(0, min(listing_chars, 24000))
        for name, definition in sorted(self.optional.items()):
            line = f"{name}: {str(definition['function'].get('description', ''))[:120]}"
            if len(line) + 1 > remaining:
                break
            listing.append(line)
            remaining -= len(line) + 1
        overview = "\n".join(listing)
        search = _schema(
            "tool_search",
            f"Search the optional tools available in this session by purpose. No tools execute. Describe a result for its argument schema, then call it. No match means no suitable selected tool. Catalog excerpt ({len(self.optional)} tools total):\n{overview}",
            {
                "queries": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 7,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            ["queries"],
        )
        describe = _schema(
            "tool_describe",
            "Read exact schemas for selected optional tools before calling them.",
            {
                "names": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 10,
                }
            },
            ["names"],
        )
        call = _schema(
            "tool_call",
            "Execute selected optional tools using their declared schemas and normal permissions. Batch calls execute sequentially; all arguments are validated before any execution.",
            {
                "calls": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "arguments": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["name", "arguments"],
                        "additionalProperties": False,
                    },
                }
            },
            ["calls"],
        )
        return [*self.direct, search, describe, call]

    def search(self, queries: object, limit: object = 5) -> list[dict[str, Any]]:
        queries = _strings(queries, maximum=7, label="queries")
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError("limit must be an integer from 1 to 25")
        documents = {}
        for name, definition in self.optional.items():
            function = definition["function"]
            parameters = function.get("parameters", {})
            properties = (
                parameters.get("properties", {}) if isinstance(parameters, dict) else {}
            )
            if not isinstance(properties, dict):
                properties = {}
            documents[name] = Counter(
                _terms(
                    " ".join([
                        name,
                        name,
                        str(function.get("description", "")),
                        *properties,
                    ])
                )
            )
        average = (
            sum(sum(doc.values()) for doc in documents.values())
            / max(1, len(documents))
            or 1
        )
        frequencies = Counter(term for doc in documents.values() for term in doc)
        results = []
        for query in queries:
            terms = set(_terms(query))
            ranked = []
            for name, doc in documents.items():
                overlap = terms & doc.keys()
                # Long speculative queries must match a meaningful share of their
                # content words; a lone incidental word must not invent a tool.
                if not overlap or (
                    len(terms) >= 6 and len(overlap) / len(terms) < 0.25
                ):
                    continue
                score = 0.0
                for term in overlap:
                    frequency = frequencies[term]
                    idf = math.log(
                        1 + (len(documents) - frequency + 0.5) / (frequency + 0.5)
                    )
                    score += (
                        idf
                        * doc[term]
                        * 2.2
                        / (
                            doc[term]
                            + 1.2 * (0.25 + 0.75 * sum(doc.values()) / average)
                        )
                    )
                ranked.append((-score, name))
            results.append({
                "query": query,
                "matches": [
                    {
                        "name": name,
                        "description": self.optional[name]["function"].get(
                            "description", ""
                        ),
                    }
                    for _, name in sorted(ranked)[:limit]
                ],
            })
        return results

    def describe(self, names: object) -> list[dict[str, Any]]:
        requested = _strings(names, maximum=10, label="names")
        if any(name not in self.optional for name in requested):
            raise ValueError(
                "Requested tool is not in this session’s optional selection"
            )
        return [copy.deepcopy(self.optional[name]["function"]) for name in requested]

    def calls(self, value: object) -> list[tuple[str, dict[str, Any]]]:
        """Validate the complete batch without network resolution or side effects."""
        from jsonschema import exceptions, validators
        from referencing import Registry

        if not isinstance(value, list) or not 1 <= len(value) <= 10:
            raise ValueError("calls requires 1–10 tool requests")
        calls = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {"name", "arguments"}:
                raise ValueError("Each call requires exactly name and arguments")
            request = cast(dict[str, Any], item)
            name, arguments = request["name"], request["arguments"]
            if not isinstance(name, str) or name not in self.optional:
                raise ValueError(
                    "Requested tool is not in this session’s optional selection"
                )
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            schema = self.optional[name]["function"].get(
                "parameters", {"type": "object"}
            )
            try:
                validator = validators.validator_for(schema)
                validator.check_schema(schema)
                # An empty registry refuses external retrieval. Tool schemas must
                # never cause credential-bearing or uncontrolled network requests.
                error = next(
                    validator(schema, registry=Registry()).iter_errors(arguments), None
                )
            except exceptions.SchemaError:
                raise ValueError(f"{name}: invalid tool schema") from None
            except Exception:
                raise ValueError(
                    f"{name}: tool schema could not be resolved locally"
                ) from None
            if error is not None:
                raise ValueError(
                    f"{name}: arguments violate {error.validator} at {list(error.absolute_path)}"
                )
            calls.append((name, copy.deepcopy(arguments)))
        return calls
