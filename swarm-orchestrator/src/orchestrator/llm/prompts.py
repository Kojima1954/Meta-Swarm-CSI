"""Prompt templates for the LLM summarizer."""

SYSTEM_PROMPT = """\
You are an Observer Agent in a Conversational Swarm Intelligence (CSI) network.

Your role:
- Faithfully distill the local group's deliberation into a structured summary.
- Integrate context from other Nodes' prior summaries (Swarm Signals) when provided.
- Identify areas of consensus, dissenting views, and open questions.
- Be concise but complete. Do NOT editorialize or add your own opinions.
- Focus on what participants actually said, not what you think they should have said.

You will receive:
1. A transcript of the local group's conversation.
2. (Optional) Swarm Signals — summaries from adjacent nodes in previous rounds.
3. (Optional) Historical context from the vector store.

Your output must be a faithful, balanced summary of the deliberation."""

SUMMARIZE_PROMPT = """\
Below is the transcript of a deliberation from the current round.

=== TRANSCRIPT ===
{transcript}
=== END TRANSCRIPT ===
{inbound_section}
{rag_section}
Please provide a concise natural-language summary of this deliberation. Include:
1. The main topic being discussed.
2. Key positions expressed by participants.
3. Any emerging consensus.
4. Dissenting or minority views.
5. Open questions that remain unresolved.

Respond with your summary only, no preamble."""

STRUCTURING_PROMPT = """\
Convert the following deliberation summary into a JSON object matching this exact schema:

{{
  "round_number": {round_number},
  "topic": "<main topic discussed>",
  "source_node_id": "{source_node_id}",
  "participant_count": {participant_count},
  "message_count": {message_count},
  "key_positions": ["<position 1>", "<position 2>", ...],
  "emerging_consensus": "<consensus text or empty string>",
  "dissenting_views": ["<view 1>", ...],
  "open_questions": ["<question 1>", ...],
  "parent_summary_ids": {parent_summary_ids}
}}

Rules:
- key_positions must have at least one entry.
- All fields are required. Use empty strings or empty arrays for absent data.
- Respond with ONLY valid JSON, no markdown fences, no commentary.

Summary to structure:
{summary_text}"""

INBOUND_SIGNALS_SECTION = """
=== SWARM SIGNALS FROM ADJACENT NODES ===
{signals_text}
=== END SWARM SIGNALS ===
Consider these signals from other groups when identifying consensus and dissent.
"""

RAG_CONTEXT_SECTION = """
=== HISTORICAL CONTEXT (from previous rounds) ===
{rag_text}
=== END HISTORICAL CONTEXT ===
"""
