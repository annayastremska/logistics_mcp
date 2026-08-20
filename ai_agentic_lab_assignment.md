# MCP Integration: Student Assignment


### General task

Build a **domain-specific data agent** that uses external tools and data to solve a coherent user problem. Depending on the chosen domain, the agent may acquire, organize, transform, validate, compare, or act on structured or unstructured data. It must do more than answer a single lookup question: it must execute a multi-step agentic flow in which tool results affect later steps, decisions, or the final output.

You will extend the agent through two MCP connections:

1. **An existing MCP server** selected from the approved list: Obsidian MCP, Microsoft Playwright MCP, or Weather MCP. This connection gives the agent access to an external environment or live data source such as an Obsidian vault, a public web interface, or current weather data.
2. **A custom MCP server that you design and implement** for a data domain of your choice. It must provide domain-specific operations over a relevant public API, local dataset, or downloadable dataset.

The two servers must participate in a meaningful overall agent workflow. They do not need to operate on the same data source, but their roles must be coherent within the selected use case. For example, an agent might read notes from Obsidian and validate them against a domain dataset, collect information from a public website and perform structured comparison or policy checks, or use weather data to revise a plan produced from local activity data.

The purpose of the assignment is to demonstrate both sides of MCP work: integrating and reasoning about an existing external connection, and designing a reliable, model-usable MCP interface for a new data domain.

### Context

In this assignment, you will implement the agent and extend it with two Model Context Protocol (MCP) connections:

1. one existing MCP server selected from the approved list; and
2. one custom MCP server designed and implemented by you.

The goal is not merely to make two tool calls. You must demonstrate that you can configure an external MCP connection, understand the contracts it exposes, handle a connection or tool failure, and design a useful MCP server for your own agent.

### Learning outcome

After completing this assignment, you will be able to integrate an agent with an existing MCP server and design, implement, document, and justify a custom MCP server with reliable, model-usable tool contracts.

### Available technologies

You have access to OpenRouter for model inference where the chosen stack supports it. For **agent implementation**, you may use one of the following frameworks (or another agent framework or MCP SDK if you can explain and reproduce your implementation):

| Framework | Role in this assignment | Starting points |
|---|---|---|
| **LangChain / LangGraph / Deep Agents** | Build agents and graph-orchestrated runs in the LangChain ecosystem; Deep Agents provides a higher-level agent harness on that stack | [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview), [Managed Deep Agents](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview) |
| **Google Agent Development Kit (ADK)** | Code-first agents, multi-agent composition, and graph / collaborative workflows | [ADK](https://adk.dev/) |
| **Claude Agent SDK** | Anthropic agent loop with tools, subagents, sessions, and MCP | [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) |

These options are **agent-implementation frameworks**: they host planning, tool calling, MCP client wiring, and orchestration. You are not limited to a single free-form agent loop. **LLM-backed workflows**—structured multi-step graphs or pipelines that call a model and tools—may also be used **with** an agent when that better fits the domain (for example a LangGraph graph, an ADK workflow/graph agent, or Claude Agent SDK dynamic workflows / subagent orchestration). What matters for assessment is that MCP tools participate in a coherent agentic flow whose results affect later steps or final output—not which orchestration style you choose.

Assessment focuses on MCP integration and design rather than on the amount of framework-specific code. If a framework requires its own model or API path (for example Anthropic credentials for the Claude Agent SDK, or Gemini for some ADK setups), document that configuration; do not commit secrets.

## Requirements

### Part A — Connect an approved existing MCP server

Select one server from the approved list at the end of this document.

You must:

- configure the server as an MCP connection for your agent;
- successfully discover and call at least one of its tools;
- incorporate at least one of its tools into an agent flow, so that a tool result is used by a later step or affects the agent's final output or action;
- inspect its exposed tool contract and explain:
  - the tool name and model-facing description;
  - its arguments and their constraints;
  - the returned content or structured result;
  - likely error conditions and side effects;
- explain why this server has a reasonable role in your project; and
- demonstrate one realistic failure during the defence/demo, such as an unavailable server, an inaccessible configured resource, invalid tool input, or a failed connection. Show how the agent or surrounding application reports or handles the failure.

A connection that is configured but never successfully called does not satisfy this part. A disconnected demonstration call that has no effect on an agent flow is also insufficient.

### Part B — Design and implement a custom MCP server

Create a custom MCP server that supports your agent's domain.

The server must:

- run in a process separate from the agent;
- be startable independently during the defence/demo;
- expose at least three distinct tools that satisfy the substantive-tool criteria below;
- expose explicit input and output schemas for every tool;
- include at least one tool that accesses a primary data source relevant to your project;
- use either:
  - a public API that does not require authentication, or
  - a local or downloadable dataset;
- be used by the agent in a complete, meaningful workflow; and
- return errors in a form that lets the caller distinguish failure from a successful empty result.

### What counts as a substantive tool

A custom tool counts toward the required three only when all of the following are true:

1. **Domain purpose:** it performs an operation that is recognizably useful in the chosen domain, not generic plumbing that could be copied unchanged into almost any project.
2. **Meaningful processing or action:** it applies domain rules, computation, validation, transformation, comparison, planning, state change, or controlled interaction with a data source. Merely returning stored text is insufficient.
3. **Designed contract:** its inputs and outputs express meaningful domain concepts and constraints rather than only accepting an unrestricted string or dictionary.
4. **Distinct responsibility:** it has a different purpose from the other tools. Changing only a fixed parameter, data category, or output format does not create a separate tool.
5. **Observable contribution:** its result or side effect can be shown to influence the agent workflow.

The following may be useful implementation helpers, but do **not** count by themselves toward the three required tools:

- reading or writing an arbitrary file;
- generic HTTP `GET`/`POST` wrappers;
- returning a fixed prompt or hard-coded response;
- listing all rows, files, or records without domain processing;
- unrestricted SQL execution;
- generic vector-store insertion or similarity search;
- thin wrappers that expose an API endpoint without adding a model-appropriate contract; or
- three search tools differentiated only by source, filter, or record type.

A retrieval or search tool may count as **one** of the three when it has a well-constrained, domain-relevant contract. However, a conventional “ingest documents → embed → similarity search → answer” RAG pipeline on its own does not satisfy the custom-server design requirement.

Examples of more substantive tool sets include:

- **Course-planning agent:** validate a proposed study plan against prerequisites, detect timetable conflicts, and suggest feasible substitutions under credit constraints.
- **Scientific-experiment agent:** validate an experiment configuration, estimate resource requirements from recorded benchmark data, and compare completed runs against a stated hypothesis.
- **Sustainability or FinOps agent:** attribute costs to projects using domain rules, detect policy violations or anomalous changes, and simulate the effect of a proposed optimization.
- **Game assistant:** validate a game state, enumerate legal actions under the rules, and evaluate a proposed move using explicit domain heuristics.
- **Public-data analysis agent:** compute a domain indicator from source data, compare entities with controlled normalization, and test whether a user-defined condition is supported by the data.
- **Personal collection agent:** detect duplicate or conflicting entries, evaluate an item against collection rules, and construct a constrained acquisition or organization plan.

These are patterns, not required domains or implementations. A student may include retrieval, but at least two of the three required tools must do something other than record/document search or retrieval.

### Worked project example — reserved topic (may not be submitted)

The following project illustrates the expected scope and level of integration. It is a valid example of the assignment, but **students may not submit this specific topic or a lightly renamed variation of it**. You must design a project in a different domain or with a substantially different problem and workflow.

**Automatic research agent.** The agent receives a research objective and iteratively proposes, runs, evaluates, and records computational experiments. The outcome of each completed experiment affects what the agent attempts next. For example, after a run it may compare the result with the current best result and the stated hypothesis, identify whether the change helped, and then revise one controlled part of the next experiment configuration.

One possible architecture is:

- **Existing MCP server — Obsidian MCP:** the agent reads the current research objective, constraints, and previous conclusions from an Obsidian vault. After evaluating a run, it writes or updates a human-readable experiment note containing the configuration, result, interpretation, and proposed next step. The notes form a research log, not merely a copy of raw console output.
- **Custom Experiment MCP server:** a separate process exposes controlled operations over experiment configurations, execution, and recorded results. It may use a small local benchmark dataset and a deterministic or resource-limited training/evaluation script so the workflow can be reproduced during the defence.

An appropriate custom tool set could include:

1. `validate_experiment_config` — checks a structured configuration against allowed models, hyperparameter ranges, dataset constraints, and the requirement that the proposed run changes only permitted variables. It returns validation errors and a normalized configuration.
2. `run_experiment` — launches an experiment from a validated configuration, assigns a run ID, and returns structured status, metrics, runtime, and artifact references. Its schema must constrain resource-intensive parameters and make execution side effects explicit.
3. `compare_experiment_runs` — compares one or more completed runs against a baseline and a stated hypothesis, computes metric differences, and returns structured evidence about whether the hypothesis is supported, contradicted, or still inconclusive.
4. `record_experiment_decision` — stores the selected conclusion and next-step rationale with links to the relevant run IDs, while preventing duplicate or inconsistent records. This may be included as a fourth tool, but a generic “write text to a log” tool would not count as substantive by itself.

A complete agent flow might be:

1. read the research objective and previous conclusions through Obsidian MCP;
2. propose the next experiment based on the recorded evidence;
3. validate the proposed configuration through the custom MCP server;
4. run the experiment only if validation succeeds;
5. compare the new run with the baseline or current best run;
6. record the configuration, metrics, comparison, conclusion, and proposed next step in the experiment store and Obsidian research log; and
7. use that conclusion to determine the next experiment or stop when a defined budget or stopping condition is reached.

The defence could show one successful iteration and one failure, such as an invalid hyperparameter, a missing dataset, an unavailable Obsidian vault, or an attempted run that exceeds the configured resource budget. The important feature is the feedback loop: experiment results must influence the next decision. A fixed sequence of preselected runs followed by generic logging would not demonstrate the intended agentic behavior.

Again, this project is provided as a concrete design example only. **The automatic research/experiment agent topic is reserved and is not an allowed submission topic.**

### Part C — Tool-contract documentation

Document every custom tool using the following structure:

| Contract element | Required content |
|---|---|
| Name | Exact MCP tool name |
| Purpose | What the tool does and when the model should use it |
| Model-facing description | Exact description exposed through MCP |
| Input schema | Fields, types, required/optional status, constraints, and defaults |
| Output schema | Fields, types, and meaning of successful results |
| Error conditions | Expected failures and how each is represented |
| Side effects | Files, state, network calls, or other changes; write “none” where applicable |
| Example | One representative input and output pair |

Also document the selected existing server and at least one of its tools. You may reference its official documentation for details, but your explanation must be written in the context of your own project and configuration.

### Part D — Operational requirements

- Do not commit credentials, tokens, or secrets.
- Use environment variables or an ignored local configuration file for any environment-specific configuration.
- Respect published API rate limits.
- If the custom server calls a network API, include recorded genuine API responses as fixtures and provide a documented replay/offline mode for the demonstration.
- Fixtures must preserve the normal parsing and processing path. A conditional branch that simply returns a prewritten “correct answer” is not an acceptable fallback.
- If the custom server uses a local or downloadable dataset and does not require network access at runtime, the prepared dataset serves as the deterministic demo input; API-response fixtures are not additionally required.
- The repository must contain all instructions and non-sensitive resources required to reproduce the demonstration.

## Submission

Submit one source repository containing:

1. the agent integration and MCP configuration, with secrets removed;
2. the custom MCP server source code;
3. a `README` with prerequisites, installation, configuration, and independent start commands for the agent and custom server;
4. tool-contract documentation;
5. the recorded API fixtures and replay instructions, when a network API is used;
6. a short design rationale explaining:
   - why the existing server is relevant;
   - why each custom tool belongs at the MCP boundary;
   - how the tool set supports the agent workflow;
   - the main design trade-offs and known limitations; and
7. a defence/demo checklist or script.

Automated tests are encouraged but are not a required submission artifact.

## Demonstration and independent defence

Choose one of the following formats:

- **Live defence:** demonstrate and explain the system synchronously to the instructor.
- **Recorded video defence:** submit a 10–15 minute video that follows the same sequence and evidentiary standard as the live defence. The recording must include continuous screen capture, the student's camera, and the student's spoken explanation. The implementation, tool calls, outputs, and failure behavior must be readable in the recording. The video should be recorded as one continuous demonstration; trimming only the beginning or end is acceptable, but combining separately recorded successful fragments is not.

In either format, the work must be demonstrated and explained independently by the student.

During the demonstration, you must:

1. start the custom MCP server independently from the agent;
2. show that the agent discovers both MCP connections;
3. invoke a tool from the approved existing server successfully;
4. run an agent flow in which the existing server's result affects a later step or final output;
5. briefly explain that tool's contract and the server's role in the flow;
6. run one complete agent workflow that uses the custom server;
7. show evidence that at least three custom tools are exposed;
8. explain one important custom tool contract and design decision;
9. demonstrate one realistic failure involving the existing MCP server or its tool and show the resulting behavior;

The instructor may ask you to vary one valid input, provide one invalid input, identify a side effect, or explain where a returned value originated.

### Defence format and timing

The demonstration is an individual 10–15 minute defence, whether delivered live or by recorded video. The student must operate and explain the submitted system independently. During the defence, the student may use the submitted repository, its documentation, prepared demo data, and normal development tools, but may not ask another person or an AI assistant to generate explanations, diagnose the system, or modify the implementation on their behalf.

The defence should normally use the following timing:

| Segment | Suggested time |
|---|---:|
| Independent startup and architecture overview | 2 minutes |
| Existing MCP server inside an agent flow | 2–3 minutes |
| Custom MCP end-to-end workflow | 3–4 minutes |
| Failure scenario and fixture/offline mode where applicable | 2 minutes |
| Instructor questions and one small variation | 3–4 minutes |

In a live defence, the instructor may ask the student to use a different valid input, trigger an invalid-input case, trace one value from source to final output, or make a small configuration-level change. In a recorded defence, the student must proactively demonstrate at least one changed valid input and one invalid or failure input, and trace at least one value from its source to the final output. The instructor may request a short follow-up clarification if required evidence is missing or unclear. The purpose is to verify understanding and authorship, not to require substantial live coding.

## Explicitly unacceptable submissions

The following do not satisfy the assignment:

- an existing MCP connection that is configured but unused;
- a custom “server” implemented only as functions inside the agent process;
- hard-coded demo answers presented as tool results;
- secrets committed to the repository or embedded in source code; or
- an external server outside the approved list, or an unmaintained/unverifiable substitute used without prior written approval.

## Assessment rubric — 100 points

### 1. MCP architecture and protocol correctness — 25 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 23–25 | Both connections initialize correctly; the custom server is independently startable and process-separated; tool discovery and invocation follow MCP correctly; configuration is reproducible; boundaries between agent, MCP client, server, and data source are clear. |
| Competent | 18–22 | Core architecture and protocol use are correct, with minor setup, lifecycle, or reproducibility weaknesses. |
| Developing | 10–17 | Partial integration works, but there are substantial protocol, process-separation, configuration, or reproducibility problems. |
| Insufficient | 0–9 | One connection is absent/non-functional, the custom server is in-process, or MCP is not meaningfully used. |

### 2. Documentation and design rationale — 25 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 23–25 | Complete contracts for all custom tools; accurate explanation of an existing tool; clear setup instructions; design choices, boundaries, trade-offs, limitations, errors, and side effects are explained specifically and convincingly. |
| Competent | 18–22 | Documentation is usable and mostly complete, but some contract details or design reasoning lack precision. |
| Developing | 10–17 | Basic documentation exists but omits important schema, behavior, setup, or rationale details. |
| Insufficient | 0–9 | Documentation cannot support evaluation or reproduction, or descriptions substantially contradict behavior. |

### 3. Custom tool and schema design — 18 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 16–18 | At least three substantive, distinct tools solve appropriate domain problems; at least two go beyond search/retrieval; names and model-facing descriptions guide correct selection; schemas are explicit, constrained, coherent, and practical; outputs are structured and usable. |
| Competent | 13–15 | Tools are useful and schemas are mostly sound, with minor ambiguity, redundancy, or under-specification. |
| Developing | 7–12 | Tool set works but contains weak boundaries, superficial overlap, vague descriptions, or poorly constrained schemas. |
| Insufficient | 0–6 | Fewer than three valid tools, no qualifying data-source tool, or schemas/behavior are unusable. |

### 4. Integration into the agent workflow — 14 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 13–14 | Both the existing connection and custom tools participate in coherent agentic flows (free-form agent loop and/or structured LLM workflow used with an agent); tool results influence subsequent behavior or final results; the integrations are clearly motivated. |
| Competent | 10–12 | Complete flows work and use both servers meaningfully, with limited orchestration or weak use of some results. |
| Developing | 5–9 | Calls occur but one connection resembles an isolated showcase or has little effect on a flow. |
| Insufficient | 0–4 | The agent does not meaningfully incorporate one or both servers into its flows. |

### 5. Existing-server integration and failure demonstration — 10 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 9–10 | Successful configuration, discovery, invocation, and incorporation into an agent flow are shown; the role and one contract are explained accurately; a realistic failure is reproduced and surfaced clearly. |
| Competent | 7–8 | Successful use and failure demonstration are present, with minor gaps in explanation or handling. |
| Developing | 4–6 | Connection works only partially, justification is weak, or the failure demonstration is artificial/unclear. |
| Insufficient | 0–3 | No successful call, no credible failure demonstration, or no justified role. |

### 6. Operational robustness and responsible data access — 8 points

| Performance | Points | Evidence |
|---|---:|---|
| Excellent | 8 | Configuration is safe; secrets are absent; rate limits are respected; errors are distinguishable; fixture replay is faithful and reproducible where required; side effects are controlled. |
| Competent | 6–7 | Requirements are met with minor weaknesses in error behavior, replay usability, or configuration. |
| Developing | 3–5 | The demo works, but robustness, fixture fidelity, rate-limit handling, or configuration has material weaknesses. |
| Insufficient | 0–2 | Unsafe configuration, missing required fallback, unreliable demonstration, or serious unmanaged side effects. |

### Minimum-condition rule

A submission cannot receive more than 59/100 if any of the following is true:

- fewer than three qualifying custom tools are exposed;
- no qualifying primary data-source tool exists;
- either MCP connection cannot be called successfully;
- the agent does not incorporate both the existing and custom servers into agent flows.

## Approved existing MCP servers

Use the exact maintained project/package linked below. Archived versions, similarly named packages, and unofficial forks are not automatically approved.

| Server | Good fit | Typical failure to demonstrate | Important setup/safety boundary |
|---|---|---|---|
| [Obsidian Local REST API MCP server](https://github.com/coddingtonbear/obsidian-local-rest-api) | Agents that read, search, organize, or update notes and structured knowledge in an Obsidian vault | Stop Obsidian/the MCP endpoint, use an invalid API key, or request a missing note | Use a dedicated demonstration vault containing no sensitive notes; do not expose a personal vault |
| [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | Agents that need structured interaction with a public web interface | Unreachable page, missing element, blocked navigation, or browser startup failure | Use only instructor-approved public pages; do not enter personal credentials or perform irreversible actions |
| [OpenWeather MCP server](https://github.com/mschneider82/mcp-openweather) | Agents whose decisions or plans depend on current weather or a five-day forecast | Missing API key, invalid city, API timeout, or unavailable server | Store `OWM_API_KEY` only in an environment variable; prepare and activate the key before the defence |

Use the exact instructor-tested version or commit announced for the course. The marketplace page is not the canonical source: follow the linked repository and course setup instructions. Another existing MCP server may be used only with prior written instructor approval.

