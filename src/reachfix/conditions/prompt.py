"""Build the advisory-extraction prompts from the schema.

Edge and node descriptions, property names and category values are read
off the loaded schema, so the prompt can't drift from the output model
built from the same file. The few-shot examples are invented advisories,
not corpus ones, so they can't leak answers into an evaluation.
"""

from ..extraction.schema import Schema
from .model import object_node_types

_FEW_SHOT_EXAMPLES = """\
Example 1:
Text: "### Impact
When the `allowUnsafeEval` option is enabled, templates compiled from \
user-supplied strings can run arbitrary code. Applications that only \
compile templates shipped with the application are not affected."
Output:
{"extractions": [\
{"relation": "EXPLOITABLE_WHEN", "text": "the `allowUnsafeEval` option is enabled", \
"category": "configuration", "evidence": "When the `allowUnsafeEval` option is enabled", "confidence": 0.95}, \
{"relation": "EXPLOITABLE_WHEN", "text": "the application compiles templates from user-supplied strings", \
"category": "input_source", "evidence": "templates compiled from user-supplied strings", "confidence": 0.9}]}

Example 2:
Text: "Versions of fast-merge before 2.3.1 are vulnerable to prototype \
pollution. ### Patches
Upgrade to 2.3.1 or later."
Output:
{"extractions": []}

Example 3:
Text: "On Windows, paths containing backslashes bypass the directory \
traversal check in `serveStatic()`, letting a remote attacker read files \
outside the served root."
Output:
{"extractions": [\
{"relation": "EXPLOITABLE_WHEN", "text": "the server runs on Windows", \
"category": "platform", "evidence": "On Windows", "confidence": 0.95}, \
{"relation": "EXPLOITABLE_WHEN", "text": "the application serves files with `serveStatic()`", \
"category": "api_usage", "evidence": "the directory traversal check in `serveStatic()`", "confidence": 0.85}]}
"""


def _describe_edges(schema: Schema) -> str:
    return "\n".join(
        f"- {name} ({'|'.join(edge.subject_types)} -> {'|'.join(edge.object_types)}): {edge.description}"
        for name, edge in schema.llm_edge_types().items()
    )


def _describe_objects(schema: Schema) -> str:
    lines = []
    for type_name in object_node_types(schema):
        node = schema.node_types[type_name]
        lines.append(f"- {type_name}: {node.description}")
        for prop, values in node.property_values.items():
            lines.append(f"  `{prop}` must be one of:")
            lines.extend(f"    - {value}: {desc}" for value, desc in values.items())
    return "\n".join(lines)


def build_system_prompt(schema: Schema) -> str:
    object_fields = ", ".join(
        f'"{p}"' for t in object_node_types(schema) for p in schema.node_types[t].properties
    )
    return f"""You extract exploitability preconditions from software security \
advisories. The advisory is the subject of every relation, so you only return \
the object. Use only this vocabulary and never invent a relation or category.

Relations:
{_describe_edges(schema)}

Objects:
{_describe_objects(schema)}

Rules:
- Extract a condition only if the text says it must hold for the flaw to be \
exploitable: a required input source, a non-default setting, a specific API \
or feature in use, a platform. Do not infer conditions from the vulnerability \
class or from general knowledge.
- A condition describes the victim application or its environment (what \
it does, how it is configured, where it runs), never an attacker's step. \
"The attacker sends a long header" is not a condition. "The server accepts \
requests from untrusted clients" is.
- Proof-of-concept code shows attacker steps. Don't extract conditions from \
it unless the prose around it states a precondition.
- The affected version range, the impact, credits and the fix are not conditions.
- A workaround is not a condition, unless the text says the flaw only occurs \
without it.
- If the text says every use of the package is affected, or states no \
precondition, return an empty list.
- `text` is a short, standalone statement about the application or its \
environment, e.g. "the application passes untrusted input to `parse()`".
- `evidence` must be copied verbatim from the given text (a phrase or \
sentence, not a paraphrase). It is checked against the text, and conditions \
whose evidence is not found are discarded.
- One condition per distinct precondition. Don't repeat one in other words.
- confidence is your calibrated estimate (0.0-1.0) that the text states \
this precondition.

{_FEW_SHOT_EXAMPLES}
Return only a JSON object: {{"extractions": [...]}}, where each item has \
"relation", {object_fields}, "evidence" and "confidence"."""


def build_user_prompt(chunk: dict) -> str:
    packages = ", ".join(chunk.get("affected_packages", [])) or "unknown"
    return (
        f"Advisory: {chunk['doc_id']}\n"
        f"Affected packages: {packages}\n"
        f"Summary: {chunk.get('summary', '')}\n\n"
        f"Text:\n{chunk['text']}"
    )
