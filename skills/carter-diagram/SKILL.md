---
name: carter-diagram
description: Generate architecture diagrams using Mermaid notation from descriptions or code
argument-hint: "[system or component to diagram]"
---

<objective>
Create clear, accurate architecture diagrams in Mermaid notation based on descriptions, code, or existing infrastructure.
</objective>

<diagram-types>

## Supported Diagram Types

Choose the most appropriate type for the request:

| Type | Mermaid Syntax | Use When |
|------|---------------|----------|
| System context | `graph TD` | Showing how a system interacts with users and external systems |
| Component | `graph TD` | Showing internal components and their relationships |
| Sequence | `sequenceDiagram` | Showing request/response flows and timing |
| Deployment | `graph TD` | Showing infrastructure, networks, cloud resources |
| State | `stateDiagram-v2` | Showing state machines and transitions |
| Flow | `flowchart TD` | Showing decision trees, CI/CD pipelines, workflows |
| ER | `erDiagram` | Showing data models and entity relationships |

</diagram-types>

<guidelines>

## Diagram Guidelines

- **Label everything** — Nodes, edges, and groups should have descriptive labels.
- **Use subgraphs** for logical grouping (VPCs, services, bounded contexts).
- **Show data flow direction** — Use arrows to indicate which way data/requests flow.
- **Include protocols** — Label edges with protocols (HTTP, gRPC, AMQP, TCP).
- **Color-code** by concern when helpful (e.g., public vs private, read vs write).
- **Keep it readable** — Split complex systems into multiple diagrams rather than one massive one.
- **Explore first** — If given a codebase, read the code to understand the actual architecture before diagramming.

## Output Format

Provide the Mermaid code block and a brief explanation of what the diagram shows:

```markdown
## [Diagram Title]

[1-2 sentence description]

```mermaid
[diagram code]
```

### Key Points
- [Notable aspects of the architecture]
```

</guidelines>
