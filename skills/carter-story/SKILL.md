---
name: carter-story
description: Write warm, precise, audience-aware public-facing narrative — announcements, launch posts, release narratives, and external storytelling. Use for outward-facing prose, not internal docs.
---

<objective>
Turn technical work into public-facing narrative that is warm, clear, and honest —
the kind of writing a person is glad to read. Lead with what matters to the
reader, ground every claim in something real, and never oversell.

**Language:** all public-facing narrative is written in English, whatever language the user chats in.
</objective>

<delegation>

## Boundaries

- **Redaction is not done here.** The `carter-narrator` agent applies redaction
  rules before anything ships. This skill assumes its input is already cleared, or
  flags uncertain values for the narrator to handle.
- **Internal/developer docs → `carter-docs`.** Story is for *external* narrative
  (announcements, launch posts), not READMEs, changelogs, or reference.
- **Slides / formatted deliverables → `pptx` / `docx`.** Story writes the words;
  those skills build the artifact.

</delegation>

<audience>

## Audience Register

Tune tone and depth to the reader. Same facts, different framing.

| Audience | They care about | Tone | Depth |
|----------|-----------------|------|-------|
| **Developers** | What it does, why it's better, how to try it | Peer-to-peer, concrete | Technical specifics, code/links |
| **Users / customers** | What changes for them, benefit | Warm, plain-language | Outcomes over mechanism |
| **Executives / stakeholders** | Impact, value, direction | Confident, succinct | Headline + supporting points |
| **Community / public** | The story, the why, what's next | Inviting, human | Narrative arc, minimal jargon |

State or infer the audience before writing; when unclear, ask.

</audience>

<craft>

## Craft

- **Lead with the reader's why.** Open on what changed *for them*, not on internal
  milestones.
- **Write for the reader, not the author.** Assume no shared context: define terms,
  expand acronyms, and never lean on prior conversations or internal knowledge the
  reader doesn't have.
- **Narrative arc.** Context → tension/problem → what was done → what it means now.
  Even a short post benefits from this shape.
- **Concrete over abstract.** One real example beats three adjectives. Show the
  thing working.
- **Warm, not breathless.** Confidence without hype. No "revolutionary,"
  "game-changing," or superlatives the work doesn't earn.
- **Honest.** Name limits and what's next. Trust is the point; false praise (of a
  product or a person) erodes it.
- **Read it aloud.** If a sentence is hard to say, rewrite it.

</craft>

<output-format>

## Output Format

Produce the narrative directly, shaped for its surface (blog post, release note,
announcement, Slack/social draft). Include a suggested title/headline. No
meta-commentary about the writing.

If any value looks sensitive (internal URL, figure, name, secret), mark it
`[REDACTED?]` and note it for the narrator's redaction pass rather than guessing.

</output-format>

<guidelines>
- Identify the audience first; tune tone and depth to the register table.
- Lead with reader value; use a narrative arc; ground claims in concrete examples.
- Warm and honest — never breathless; name limitations.
- Flag anything that may need redaction; do not apply redaction yourself.
- Hand off internal docs to `carter-docs` and slide/doc artifacts to `pptx`/`docx`.
</guidelines>
