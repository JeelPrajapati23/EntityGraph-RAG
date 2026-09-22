"""Build the extraction system prompt from the loaded schema.

Node/edge type names and descriptions are read straight off the Schema
object (itself parsed from schema/v1.yaml) so the prompt can never drift
out of sync with the Literal types build_triple_model() generates from the
same file.
"""

from .schema import Schema

_FEW_SHOT_EXAMPLES = """\
Example 1:
Text: "TSMC is the primary foundry partner fabricating NVIDIA's H100 and \
Blackwell GPUs on its advanced process nodes."
Triples:
[{"subject": "TSMC", "subject_type": "Company", "relation": "SUPPLIES", \
"object": "NVIDIA", "object_type": "Company", "confidence": 0.95}]

Example 2:
Text: "Jensen Huang has served as President and Chief Executive Officer of \
NVIDIA since its founding in 1993."
Triples:
[{"subject": "Jensen Huang", "subject_type": "Person", "relation": \
"EXECUTIVE_OF", "object": "NVIDIA", "object_type": "Company", \
"confidence": 0.98}]

Example 3:
Text: "Our business faces intense competition from Intel, AMD, and \
Qualcomm in the markets for GPUs, CPUs, and mobile processors."
Triples:
[{"subject": "NVIDIA", "subject_type": "Company", "relation": \
"COMPETES_WITH", "object": "Intel", "object_type": "Company", \
"confidence": 0.9}, {"subject": "NVIDIA", "subject_type": "Company", \
"relation": "COMPETES_WITH", "object": "AMD", "object_type": "Company", \
"confidence": 0.9}, {"subject": "NVIDIA", "subject_type": "Company", \
"relation": "COMPETES_WITH", "object": "Qualcomm", "object_type": \
"Company", "confidence": 0.9}]
"""


def _describe_node_types(schema: Schema) -> str:
    lines = []
    for node in schema.node_types.values():
        lines.append(f"- {node.name}: {node.description}")
    return "\n".join(lines)


def _describe_edge_types(schema: Schema) -> str:
    lines = []
    for edge in schema.edge_types.values():
        subj = "|".join(edge.subject_types)
        obj = "|".join(edge.object_types)
        symmetric = " (symmetric)" if edge.symmetric else ""
        lines.append(f"- {edge.name} ({subj} -> {obj}){symmetric}: {edge.description}")
    return "\n".join(lines)


def build_system_prompt(schema: Schema) -> str:
    return f"""You are an information-extraction system for financial documents \
(SEC filings and earnings-call transcripts). Extract entity-relation-entity \
triples from the given text chunk, strictly using this fixed vocabulary — \
never invent a node type, edge type, or relation not listed here.

Node types:
{_describe_node_types(schema)}

Edge types (subject_type -> object_type: description):
{_describe_edge_types(schema)}

Rules:
- Only extract relations that are explicitly stated or clearly implied by \
the text. Do not infer from general/outside knowledge.
- Use each entity's full canonical name as it appears in the text (e.g. \
"NVIDIA Corporation" or "NVIDIA", not "the company").
- If a relation is present but doesn't fit any specific edge type above, use \
MENTIONS as a fallback rather than forcing a wrong typed relation.
- confidence is your own calibrated estimate (0.0-1.0) that the relation is \
correctly and precisely stated in the text.
- If the chunk contains no extractable relations, return an empty list.

{_FEW_SHOT_EXAMPLES}
Now extract triples from the given chunk. Return only the JSON list of \
triples, matching the schema exactly."""


def build_user_prompt(chunk_text: str) -> str:
    return f"Text:\n{chunk_text}"
