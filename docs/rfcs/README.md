# RFCs — Requests for Comments

Design proposals that explore *"should we do X?"* before a plan or code exists
([ADR-0004](../adr/0004-rfc-system.md)). An RFC is a **directory** here; status
lives in frontmatter (the directory never moves). An accepted RFC yields an ADR
(the durable decision) and then a plan (execution). Authored via the
[`carter-rfc`](../../skills/carter-rfc/SKILL.md) skill.

| Status | RFC | Tags |
|--------|-----|------|
| ✅ accepted | [0001-rfc-system](0001-rfc-system/) | rfc, process |
| ✅ accepted | [0002-risk-based-strictness-policy](0002-risk-based-strictness-policy/) *(superseded by RFC-0005)* | strictness, enforcement, security, agents, mcp, policy |
| 🚫 withdrawn | [0003-per-agent-scoped-mcp-tokens](0003-per-agent-scoped-mcp-tokens/) *(absorbed by ADR-0008 D2 + ADR-0010)* | security, mcp, tokens, secrets, policy |
| ✅ accepted | [0004-cost-context-optimization](0004-cost-context-optimization/) *(r4: decisions unbuilt; model-tier lever added)* | cost, tokens, context, mcp, models, performance, harness, billing |
| ✅ accepted | [0005-native-subagent-orchestration](0005-native-subagent-orchestration/) | agents, orchestration, subagents, dispatch, models, strictness, policy, time, copilot, vscode, opencode |
| ✅ accepted | [0006-carter-security-agent](0006-carter-security-agent/) *(→ ADR-0013)* | agents, security, defensive, authorization, threat-model, mcp, sast, sca, cve, dispatch, policy, copilot, vscode, opencode |

Status icons: ⬜ draft · 📝 review · ✅ accepted · ❌ rejected · 🚫 withdrawn.
