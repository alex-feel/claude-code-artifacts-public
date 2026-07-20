---
name: dynamic-workflow-patterns
description: Pattern taxonomy, agent role combinations, model routing, and resilience discipline for Claude Code dynamic workflows. ALWAYS load this skill before authoring or running any Workflow tool script, and ALWAYS load it when the user mentions "workflow" or "ultracode" in any form -- or when the task calls for multi-agent orchestration such as fan-out, tournaments, adversarial verification, triage at scale, ranking large lists, deep verification of claims, or root-cause hunting; do not hand-roll a workflow from memory when this skill applies. Also covers surviving server errors such as HTTP 529, recovering interrupted runs, and honoring token budgets.
---

# Dynamic Workflow Patterns

The Workflow tool description already teaches the script API, the opt-in rules, and the execution mechanics; every mention of those below is a one-line anchor, never a re-teach.

This skill adds what that description lacks: which pattern to pick, which agent roles to combine for each task family, which model to give each role, and how to keep a workflow alive through server errors and interruptions.

## Why Single Contexts Fail

Pattern choice and prompt design follow from knowing which failure mode the workflow defends against, so diagnose the threat before picking the shape.

**Agentic laziness.** The model declares done after partial progress, for example addressing 35 of 50 items in a review. Counter: the deterministic script, not the model, decides when work is done -- explicit item lists, loop-until-done stop conditions, and a logged record of every dropped item.

**Self-preferential bias.** The model favors its own output when asked to verify or judge it. Counter: assign verification to agents that did not produce the work -- verifiers, refuters, skeptics, and judges who never grade their own attempt.

**Goal drift.** Fidelity to the objective decays across many turns and lossy compactions, dropping edge-case requirements and don't-do-X constraints. Counter: each subagent lives in a short fresh context with the objective restated verbatim in its prompt, the script pins the original goal in args so no compaction ever touches it, and the deterministic script body holds the authoritative item list, bracket, or rule set, which survives compaction because the script replays from cache on resume.

### When Not to Use a Workflow

Workflows multiply token cost by the number of agents, so apply the does-it-really-need-more-compute test first: most routine coding tasks show none of the three failure modes, and for them the default harness is cheaper, faster, and just as correct. A routine change does not need a panel of five reviewers.

## The Six Patterns and How to Choose

| Pattern                  | Shape                                                                               | Reach for it when                                                        |
|--------------------------|-------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Classify-and-act         | A classifier labels the task or item, code routes on the label                      | Heterogeneous inputs need different treatment, or routing models by cost |
| Fan-out-and-synthesize   | Split into independent pieces, one agent each, barrier, merge                       | Many pieces would cross-contaminate one window and you need one result   |
| Adversarial verification | A separate agent tries to refute each output against a rubric                       | The producer must not grade its own work                                 |
| Generate-and-filter      | Generators produce candidates in volume, a rubric-plus-dedupe filter keeps the best | Quality comes from quantity: naming, design, ideas, taste                |
| Tournament               | N agents attempt the same task, fresh judges compare pairwise                       | Competing attempts or ranking beat dividing the work                     |
| Loop until done          | Keep spawning agents until a stop condition holds                                   | The volume of work is unknown up front                                   |

Classify-and-act deserves detail because the tool description never covers it: a classifier agent decides what the task or item IS, then deterministic code routes to specialized agents or behaviors; make the classifier return a structured schema label so routing switches on data and never string-matches free prose, and remember the same move works at the END of a workflow to grade or select output.

Generate-and-filter also gets detail: several generator agents produce candidates in volume, deliberately varied in angle, then a filter step applies a rubric plus dedupe and EXPLICITLY discards the losers -- a visible discard, never a silent drop. Do not use it when every item must be processed; that is fan-out's job.

Tournament gets detail too: N agents attempt the SAME task, each prompted to try a deliberately different approach -- they compete, they do not divide the work -- and a FRESH judge agent runs each pairwise comparison while the deterministic loop holds the bracket, so only the running order stays in context. Pairwise comparative judgment is more reliable than absolute scoring, which is the whole reason the pattern exists. For ranking tasks, keep comparing until the order is complete: the output is a full sorted list from first to last, not only a top-1 winner.

Real workflows chain patterns -- classify, fan out, adversarially verify, synthesize. Quarantine is classify-and-act with a privilege boundary; deep verification is fan-out where each unit is one claim.

## The Role Vocabulary

A role is nothing but an agent() prompt persona, but naming the role in the prompt sets the cognitive frame -- an agent prompted to DISPROVE pushes far harder than one asked to check -- while keeping each context single-purpose.

- **classifier** -- routes work or grades output; keep its output schema a tiny label so routing stays cheap and unambiguous.
- **generator** -- produces candidates or hypotheses; run several with deliberately different angles.
- **worker** -- executes one unit of the task in its own context.
- **verifier** -- checks one output against one rule or rubric; one concern per verifier.
- **refuter** -- prompted to DISPROVE, so a surviving claim means evidence, not agreement.
- **skeptic** -- re-reads each flag asking real violation or false positive; the false-positive filter.
- **judge** -- pairwise comparator or panel scorer; never judges its own attempt.
- **synthesizer** -- merges structured outputs after a barrier; the only role that sees everything.
- **hypothesis agent** -- generates a root-cause hypothesis from one disjoint evidence slice (logs, files, or data) so hypotheses never cross-contaminate.
- **quarantined reader** -- reads untrusted content with read-only tools and no privileges; emits a structured summary only.
- **trusted actor** -- holds the privileges; acts on summaries, never on raw untrusted content.
- **claim extractor** -- decomposes a document into atomic checkable claims.
- **claim checker** -- verifies exactly one claim against sources.
- **source auditor** -- audits source quality, not the claim itself.

## Use-Case Playbook

- **Migrations and refactors.** Scout inline to discover the worklist, then one worker per fix in worktree isolation, an adversarial reviewer per fix, then merge; instruct workers to avoid resource-heavy commands (full builds, container spins) so parallelism stays high on one machine.
- **Deep research.** Fan out searches across modalities, fetch sources, adversarially verify claims, synthesize a cited report; the same shape works beyond the web -- compiling a status report from team chat history, or researching how a feature works by exploring a codebase in depth.
- **Deep verification of factual claims.** A claim extractor identifies every factual claim, one claim checker per claim verifies it against sources, an optional source auditor checks that each source is itself high quality, and the results merge into a verified report; each claim flows independently through its checker and auditor stages (per-claim isolation prevents cross-claim contamination), and the final report merge is the only barrier.
- **Sorting and ranking large lists.** Pairwise tournament (fresh agent per comparison, deterministic loop holds the bracket) or bucket-rank in parallel then merge; 1000+ rows neither fit one context nor survive absolute scoring, while comparative judgment holds; the deliverable is a full ranked list.
- **Rule adherence.** One verifier agent per rule over the diff, each with a clean context, because rule blending is why single-context rule checks miss; flagged lines go to a skeptic who re-reads each flag asking real violation or false positive; only confirmed violations reach the output.
- **Rule mining (the reverse direction).** Mine recent sessions and review comments for corrections the user keeps making, cluster them with parallel agents, adversarially verify each candidate rule (would it have prevented a real mistake?), and distill the survivors into durable memory rules.
- **Root-cause investigation.** Hypothesis agents each fed a disjoint evidence slice (separate agents for logs, files, data) so no single narrative forms, then a panel of verifiers and refuters per hypothesis until one theory survives the evidence; applies beyond code -- sales drops, pipeline failures, any post-mortem.
- **Triage at scale.** The quarantine composition (next section), run continuously.
- **Exploration and taste.** Generate-and-filter against an explicit rubric -- elicit the rubric from the user first; the task completes when the review agent says the criteria are met; order or select finalists via tournament.
- **Lightweight evals.** Parallel attempts in worktrees, then comparison agents grade the outputs against a rubric -- for example evaluating and refining a just-built capability against fixed criteria.
- **Model and intelligence routing.** A classifier agent researches actual complexity BEFORE routing; see Model Routing below.

When the user names a pattern or roles in the request, honor them; when the request is vague, pick the composition from this playbook.

## The Quarantine Security Pattern

Backlog content -- support tickets, bug reports, user feedback -- is untrusted and may embed prompt injection aimed at whoever reads it.

Quarantine zone: reader agents, one per item, run with read-only tools and no privileges; they read the untrusted content and classify it, and a dedupe step checks each item against what is already tracked.

Only structured summaries cross the boundary out of quarantine -- raw untrusted content never does.

Trusted zone: a single high-privilege actor agent acts on the summaries and never sees raw content; when an item is fixable it attempts the fix and opens a PR, otherwise it escalates to a human; pair the whole workflow with recurring-interval execution to run continuously.

The reason this works: readers of untrusted content hold no privileges, so prompt injection in that content can never reach high-privilege tools -- the summary boundary is the trust boundary, and the security boundary is the workflow structure itself, not model vigilance.

## Model Routing

Fan-out multiplies token cost by width, so concentrate intelligence where judgment concentrates. Routing is about spending tokens where they buy quality, never about saving them at the price of a wrong answer: quality is the priority, and when genuinely unsure which tier a role needs, give it the stronger model.

The model option takes Claude Code's model aliases -- haiku, sonnet, opus, fable -- and each resolves to the current recommended model of its tier, so a script names the tier and stays current as models advance.

- Default is inherit: omit the model option so the session's model governs, unless a role clearly wants otherwise.
- haiku, the fast and efficient tier for simple tasks, fits high-volume mechanical roles: classification labels, dedupe checks, simple pairwise comparisons, quarantined readers spawned in bulk.
- sonnet, the everyday coding tier, fits standard workers, verifiers, and readers.
- opus, the complex-reasoning tier, fits judgment-concentrated roles -- synthesis, final judging, trusted acting, and ambiguous taste calls -- where one wrong verdict poisons everything downstream.
- fable, the most capable tier for the hardest and longest-running tasks, fits the roles where the whole workflow's value rides on one output: the final verdict of a deep root-cause hunt, architecture-level synthesis, a long-running trusted actor that must hold a thread from start to finish.

Not every role needs fable or even opus -- the strongest tier on a bulk mechanical role buys no quality, only cost -- but ties always break upward, because a wrong verdict costs more than the tokens a cheaper tier saves.

The routing-by-research move: a classifier agent first investigates the task's actual complexity -- how many files the module spans, the shape of the codebase -- and only then routes to a cheaper or stronger model, because complexity is invisible from the prompt alone: "explain how the auth module works" can be a cheap task or a hard one depending on what the classifier finds.

## Resilience: Surviving Server Errors, Dead Agents, and Interruptions

Terminal API errors such as HTTP 529 overloaded surface as null returns from agent() after the harness's own retries are exhausted, and thrown thunks resolve to null -- nulls are the failure signal, not exceptions. An agent can even complete all of its work and still die returning the result when the connection drops at the last step, so a null does not mean the attempt was worthless, only that its output never arrived.

Wrap critical agent() calls in a small retry helper that re-invokes up to N times on null, because transient overload usually clears. Keep the first attempt's prompt and opts byte-identical to the plain call so a resumed run replays it from cache, and give every later attempt a distinct label suffix and a short retry note in the prompt so each retry gets its own cache identity. This is resume-safe because the retry decision depends only on prior agent results, so control flow stays deterministic and cache-replayable.

Apply null discipline everywhere: filter(Boolean) after every parallel or pipeline harvest, and null-guard every property access on agent results (result?.field), because one dead agent must never crash the script and destroy all sibling work.

After every barrier, check quorum: compare how many results arrived against how many you launched, and when a required input is missing -- a debate missing one position, a synthesis missing one dimension -- re-run the missing item or stop loudly, never continue silently on partial inputs, because downstream stages will happily build on an incomplete picture without noticing.

Accumulate partial results: push each completed item's output into a results array as it finishes so completed work survives any later failure, and design each phase's output as the accumulated survivors, never an all-or-nothing computation.

Log every dropped item with its identity, because silent truncation is indistinguishable from completion and reintroduces agentic laziness at the script level.

```javascript
async function tryAgent(prompt, opts, attempts) {
  for (let att = 1; att <= attempts; att++) {
    const r = await agent(
      att === 1 ? prompt : `${prompt}\n(Retry ${att} after a transient server failure; produce the complete deliverable.)`,
      att === 1 ? opts : { ...opts, label: `${opts.label}:retry${att}` },
    )
    if (r) return r
    log(`${opts.label}: attempt ${att} of ${attempts} returned null`)
  }
  return null
}

const results = []
const dropped = []
const raw = await parallel(items.map(it => () => tryAgent(promptFor(it), { label: `work:${it.id}` }, 3)))
raw.forEach((r, i) => (r ? results.push(r) : dropped.push(items[i].id)))
if (dropped.length) log(`quorum ${results.length}/${items.length}; dropped: ${dropped.join(', ')}`)
```

Checkpoint at phase boundaries by keeping each phase a pure function of prior agent results, so after a crash in phase three a resume replays phases one and two from cache for free.

To recover an interrupted or partially failed run, stop it, edit the persisted script file on disk, and relaunch with that scriptPath plus resumeFromRunId; prefer edit-and-resume over a fresh restart because the cache preserves everything already paid for. The run's journal and per-agent transcripts in the workflow's transcript directory show exactly which agent died and why, so diagnose there before re-running anything.

The determinism ban on the current-time and randomness built-ins protects this same replay cache; when a timestamp or seed is genuinely needed, compute it outside the script and pass it in via args.

Guard budget-scaled loops on budget.total being set, because it is not set when the user gave no cap, and inside long loops check budget.spent() to stop cleanly and emit accumulated results before the hard ceiling makes agent() throw.

## Operations: Budgets, Quick Workflows, Recurring Runs, and Prompting

Token budgets work from the request side: phrasing like "use a 10k token budget" sets the hard ceiling the harness enforces, so surface this phrasing to users who worry about cost, and scale agent count and depth to fit the cap rather than overrunning it.

Workflows are not only for large tasks: a quick workflow, such as a fast adversarial review of one assumption, buys the anti-bias structure at small cost, so offer it when a full harness would be overkill but one failure mode still threatens.

Pair repeatable workflows -- triage, research, verification -- with recurring-interval execution and set a hard completion goal, so scheduled runs neither drift nor stop early.

When authoring a workflow or shaping a user's request into one, name the pattern, the roles, the stop condition, the output schema for any structured result, and the model tier per role: the more the request mirrors this taxonomy, the closer the generated script lands to the intended architecture.

## Saving, Sharing, and Templates

Save a good workflow by pressing "s" in the workflow menu, and check saved scripts into the user-level workflows directory so they persist across sessions and machines.

Distribute a workflow by shipping its JavaScript script files inside a skill and referencing them from that skill's instructions.

Treat shipped scripts as templates, never as scripts to run verbatim, and say so in the shipping skill's prose: adapt file paths, rule lists, rubrics, and model choices to the task at hand before running, because verbatim reuse forfeits the tailor-made advantage that makes dynamic workflows outperform static harnesses, and frozen scripts rot as tasks drift.
