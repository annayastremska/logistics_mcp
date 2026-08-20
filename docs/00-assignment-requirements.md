# Assignment Requirements — Digest

Condensed from `ai_agentic_lab_assignment.md`. This is the authoritative checklist for what must exist; the original file wins on any conflict.

## Goal

Build a **domain-specific data agent** that executes a **multi-step agentic flow** where tool results affect later steps, decisions, or the final output. A single lookup answer is not sufficient.

The agent is extended through **two MCP connections**:

1. One **approved existing** MCP server.
2. One **custom** MCP server we design and implement.

Both must play coherent roles in one overall workflow.

## Part A — Existing MCP server

Approved list (exact maintained project only; forks/archived versions not approved):

| Server | Repo |
|---|---|
| Obsidian Local REST API MCP | github.com/coddingtonbear/obsidian-local-rest-api |
| Microsoft Playwright MCP | github.com/microsoft/playwright-mcp |
| OpenWeather MCP | github.com/mschneider82/mcp-openweather |

Required:

- Configure it as an MCP connection for the agent.
- Successfully **discover and call** at least one tool.
- Incorporate at least one tool into the agent flow so its **result is used by a later step** or affects the final output/action.
- Document its tool contract: tool name and model-facing description, arguments and constraints, returned content/structured result, likely error conditions and side effects.
- Explain why this server has a reasonable role in the project.
- **Demonstrate one realistic failure** during the defence (unavailable server, inaccessible resource, invalid tool input, failed connection) and show how the failure is reported/handled.

Explicitly insufficient: a configured-but-never-called connection; a demo call disconnected from the agent flow.

## Part B — Custom MCP server

Must:

- Run in a **process separate** from the agent.
- Be **startable independently** during the defence.
- Expose **at least three distinct substantive tools**.
- Expose **explicit input and output schemas** for every tool.
- Include at least one tool that accesses a **primary data source** relevant to the project.
- Use either a **public API requiring no authentication**, or a **local/downloadable dataset**.
- Be used by the agent in a complete, meaningful workflow.
- **Return errors in a form that lets the caller distinguish failure from a successful empty result.**

### Substantive-tool criteria (all five must hold)

1. **Domain purpose** — recognizably useful in the domain, not generic plumbing.
2. **Meaningful processing or action** — domain rules, computation, validation, transformation, comparison, planning, state change, or controlled data-source interaction. Returning stored text is not enough.
3. **Designed contract** — inputs/outputs express domain concepts and constraints, not an unrestricted string or dict.
4. **Distinct responsibility** — differs in purpose from the other tools. Changing only a fixed parameter, data category, or output format does not create a separate tool.
5. **Observable contribution** — its result or side effect demonstrably influences the agent workflow.

### Does NOT count toward the three

Reading/writing an arbitrary file; generic HTTP GET/POST wrappers; fixed prompt or hard-coded response; listing all rows/files/records without domain processing; unrestricted SQL; generic vector-store insert or similarity search; thin API endpoint wrappers with no model-appropriate contract; three search tools differentiated only by source/filter/record type.

A retrieval tool may count as **one** of the three if well-constrained and domain-relevant. **At least two of the three must do something other than search/retrieval.** A conventional ingest→embed→similarity-search→answer RAG pipeline does not satisfy the design requirement.

### Reserved topic — may not be submitted

The **automatic research/experiment agent** (propose → run → evaluate → record ML experiments) is a worked example in the assignment and is explicitly forbidden as a submission, including lightly renamed variants.

## Part C — Tool-contract documentation

Every custom tool documented with exactly these elements:

| Element | Required content |
|---|---|
| Name | Exact MCP tool name |
| Purpose | What it does and when the model should use it |
| Model-facing description | Exact description exposed through MCP |
| Input schema | Fields, types, required/optional, constraints, defaults |
| Output schema | Fields, types, meaning of successful results |
| Error conditions | Expected failures and how each is represented |
| Side effects | Files, state, network calls, other changes; "none" where applicable |
| Example | One representative input/output pair |

Also document the selected existing server and at least one of its tools, written in the context of our own project and configuration.

## Part D — Operational requirements

- No credentials, tokens, or secrets committed.
- Environment variables or an ignored local config file for environment-specific configuration.
- Respect published API rate limits.
- If the custom server calls a network API: include **recorded genuine API responses as fixtures** and provide a **documented replay/offline mode**.
- **Fixtures must preserve the normal parsing and processing path.** A conditional branch returning a prewritten "correct answer" is not acceptable.
- If a local/downloadable dataset is used and no network access is needed at runtime, the prepared dataset is the deterministic demo input and API fixtures are not additionally required.
- The repository must contain all instructions and non-sensitive resources needed to reproduce the demonstration.

## Submission contents

1. Agent integration and MCP configuration, secrets removed.
2. Custom MCP server source code.
3. `README` with prerequisites, installation, configuration, and **independent start commands** for the agent and the custom server.
4. Tool-contract documentation.
5. Recorded API fixtures and replay instructions.
6. Short design rationale covering: why the existing server is relevant; why each custom tool belongs at the MCP boundary; how the tool set supports the agent workflow; main design trade-offs and known limitations.
7. Defence/demo checklist or script.

Automated tests are encouraged, not required.

## Defence — 9 required demonstrations

1. Start the custom MCP server independently from the agent.
2. Show the agent discovers **both** MCP connections.
3. Invoke a tool from the approved existing server successfully.
4. Run an agent flow where the existing server's result **affects a later step or final output**.
5. Briefly explain that tool's contract and the server's role in the flow.
6. Run one complete agent workflow that uses the custom server.
7. Show evidence that **at least three custom tools are exposed**.
8. Explain one important custom tool contract and design decision.
9. Demonstrate one realistic failure involving the existing MCP server or its tool, and the resulting behavior.

Format: individual 10–15 minute defence, live or recorded video. Recorded video requires continuous screen capture + camera + spoken explanation; stitching separately recorded successful fragments is not allowed.

**Recorded defence additionally requires, proactively:** one changed valid input, one invalid/failure input, and tracing at least one value from its source to the final output.

Suggested timing: startup + architecture 2 min · existing MCP in a flow 2–3 min · custom MCP end-to-end 3–4 min · failure + offline mode 2 min · questions and one variation 3–4 min.

The instructor may ask to vary a valid input, provide an invalid input, identify a side effect, or explain where a returned value originated.

## Explicitly unacceptable

- Existing MCP connection configured but unused.
- Custom "server" implemented as functions inside the agent process.
- Hard-coded demo answers presented as tool results.
- Secrets committed to the repository or embedded in source.
- An external server outside the approved list, or an unmaintained/unverifiable substitute, without prior written approval.

## Rubric — 100 points

| # | Criterion | Points |
|---|---|---:|
| 1 | MCP architecture and protocol correctness | 25 |
| 2 | Documentation and design rationale | 25 |
| 3 | Custom tool and schema design | 18 |
| 4 | Integration into the agent workflow | 14 |
| 5 | Existing-server integration and failure demonstration | 10 |
| 6 | Operational robustness and responsible data access | 8 |

Top band evidence, condensed:

- **(1) 23–25:** both connections initialize; custom server independently startable and process-separated; discovery and invocation follow MCP correctly; configuration reproducible; clear boundaries between agent, MCP client, server, data source.
- **(2) 23–25:** complete contracts for all custom tools; accurate explanation of an existing tool; clear setup instructions; design choices, boundaries, trade-offs, limitations, errors, side effects explained specifically.
- **(3) 16–18:** ≥3 substantive distinct tools; ≥2 beyond search/retrieval; names and descriptions guide correct selection; schemas explicit, constrained, coherent; outputs structured and usable.
- **(4) 13–14:** both connections participate in coherent agentic flows; tool results influence subsequent behavior or final results; integrations clearly motivated.
- **(5) 9–10:** successful configuration, discovery, invocation, incorporation shown; role and one contract explained accurately; realistic failure reproduced and surfaced clearly.
- **(6) 8:** safe configuration; no secrets; rate limits respected; errors distinguishable; fixture replay faithful and reproducible; side effects controlled.

## Minimum-condition rule — hard ceiling 59/100

Cannot exceed 59 points if any of these is true:

- Fewer than three qualifying custom tools are exposed.
- No qualifying primary data-source tool exists.
- Either MCP connection cannot be called successfully.
- The agent does not incorporate both the existing and custom servers into agent flows.
