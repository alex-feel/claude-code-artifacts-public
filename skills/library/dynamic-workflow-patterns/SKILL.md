---
name: dynamic-workflow-patterns
description: Pattern taxonomy, agent role combinations, model routing, unit-of-work sizing, and resilience discipline for Claude Code dynamic workflows. ALWAYS load this skill before authoring or running any Workflow tool script, and ALWAYS load it when the user mentions "workflow" or "ultracode" in any form -- or when the task calls for multi-agent orchestration such as fan-out, tournaments, adversarial verification, triage at scale, ranking large lists, deep verification of claims, or root-cause hunting; do not hand-roll a workflow from memory when this skill applies.
---

# Dynamic Workflow Patterns

The Workflow tool description already teaches the script API, the opt-in rules, and the execution mechanics; every mention of those below is a one-line anchor, never a re-teach.

This skill adds what that description lacks: which pattern to pick, which agent roles to combine for each task family, which model to give each role, how large to cut each agent's unit of work, how to behave between launch and completion, and how to keep a workflow alive through server errors, stalls, and interruptions.

## Why Single Contexts Fail

Pattern choice and prompt design follow from knowing which failure mode the workflow defends against, so diagnose the threat before picking the shape.

**Agentic laziness.** The model declares done after partial progress, for example addressing 35 of 50 items in a review. Counter: the deterministic script, not the model, decides when work is done -- explicit item lists, loop-until-done stop conditions, and a logged record of every dropped item.

**Self-preferential bias.** The model favors its own output when asked to verify or judge it. Counter: assign verification to agents that did not produce the work -- verifiers, refuters, skeptics, and judges who never grade their own attempt.

**Goal drift.** Fidelity to the objective decays across many turns and lossy compactions, dropping edge-case requirements and don't-do-X constraints. Counter: each subagent lives in a short fresh context with the objective restated verbatim in its prompt, the script pins the original goal in args so no compaction ever touches it, and the deterministic script body holds the authoritative item list, bracket, or rule set, which survives compaction because the script replays from cache on resume.

### When Not to Use a Workflow

Workflows multiply token cost by the number of agents, so apply the does-it-really-need-more-compute test first: most routine coding tasks show none of the three failure modes, and for them the default harness is cheaper, faster, and just as correct. A routine change does not need a panel of five reviewers.

The test applies per phase, not once per task: a task large enough to earn a wide research fan-out still does not earn a review panel for the three-paragraph edit that falls out of it. Size each phase's agent count to that phase's own delta and risk, and verify small deltas inline -- an ultracode or high-effort session raises the ceiling for phases that need the compute, never the floor for phases that do not.

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

Fan-out multiplies token cost by width, so concentrate intelligence where judgment concentrates. Routing spends tokens where they buy quality, never saving them at the price of a wrong answer -- but the tier is a capability dial, not a rescue. Escalate the tier when a cheaper model given full context and a well-scoped unit would still judge wrongly; when the failure is mechanical instead -- skipped items, exhausted exploration, an agent that never returned -- fix the unit's scope and budget (next section), because a stronger model does not rescue an oversized unit, it only burns longer before dying.

The model option takes Claude Code's model aliases -- haiku, sonnet, opus, fable -- and each resolves to the current recommended model of its tier, so a script names the tier and stays current as models advance; never pin dated model IDs inside a workflow script.

A model override is validated against session-level settings the script never sees -- the effort level and the thinking configuration -- and tiers differ in which combinations they accept, so a routed tier can be rejected at launch with an instant, zero-token 400 even though the session's own model runs fine. That rejection is deterministic -- retrying the same route fails identically -- so treat any instant zero-token failure as a configuration rejection, never as a dead server, and reroute the role: inherit the session model, or use a tier that has already succeeded in this run.

- haiku, the fast and efficient tier, fits high-volume mechanical roles: classification labels, dedupe checks, simple pairwise comparisons, quarantined readers spawned in bulk.
- sonnet, the everyday workhorse, fits standard workers, verifiers, readers, and claim checkers; each generation's sonnet commonly lands near the previous generation's opus on agentic work, so bulk roles lose almost no quality here while costing a fraction.
- opus, the expert tier and the recommended starting point for complex agentic work, fits judgment-concentrated roles -- synthesis, final judging, trusted acting, ambiguous taste calls -- where one wrong verdict poisons everything downstream.
- fable, the frontier tier at roughly double the opus price, is a specialist, not a better default: reserve it for the few units genuinely beyond the opus tier -- the final verdict of a deep root-cause hunt, architecture-level synthesis over a sprawling system, a long-running trusted actor that must hold one thread from start to finish. A workflow that routes every role to fable buys cost, not quality.

Route relative to the session, because unrouted agents inherit the session model. When the session itself runs fable, frontier judgment already lives in the main loop -- the orchestrator authors the script, reads every result, and writes the final synthesis -- so subagents rarely need fable at all: opus covers the judgment-concentrated stages while the frontier calls stay in the main loop. When the session runs opus, the logic inverts: route the one or two hardest units up to fable, buying frontier capability exactly where the whole run's value rides on one output. Either way, in a session on a top tier every unrouted bulk role silently becomes a top-tier agent -- the most expensive possible way to read a file -- so a wide fan-out with no model options is a routing failure, not a safe default.

The routing-by-research move: a classifier agent first investigates the task's actual complexity -- how many files the module spans, the shape of the codebase -- and only then routes to a cheaper or stronger model, because complexity is invisible from the prompt alone: "explain how the auth module works" can be a cheap task or a hard one depending on what the classifier finds. When two tiers genuinely tie for a judgment role after that investigation, break the tie upward, because a wrong verdict costs more than the tokens a cheaper tier saves; a tie on a bulk mechanical role breaks downward, because the strongest tier buys no quality there.

## Sizing the Unit of Work

Patterns decide how agents are arranged; sizing decides what one agent's unit of work contains and how much of it the agent may hold. Both stall deaths and hour-long wall-clock tails trace to badly cut units far more often than to models or patterns, so shape the unit before tuning anything else.

- **Code does the mechanical part; the agent keeps the judgment.** Pairing every failure in a log with what followed it is a deterministic join a script performs perfectly in a second, while an agent performs it slowly, partially, and at stall risk. Precompute joins, correlations, and groupings into the input, and hand the agent only the interpretation.
- **Split by the data's natural structure, never by count.** Cutting an overloaded task into groups the data itself suggests -- failure families, modules, time windows -- gives each agent a self-contained set and an independently useful answer; cutting the same work in half gives two agents that each lack context.
- **Put the exploration budget in the prompt, in words.** One sentence -- use pointed greps instead of reading large files whole, stay within about 25 tool calls, and a complete answer with three grounded findings beats an exhaustive search that never returns -- is the difference between an agent that finishes and one the runner kills.
- **Cap the output in the prompt and in the schema descriptions** -- characters per field plus maxItems on every array -- because an unbounded structured answer is itself a stall mechanism: one long, silent generation. "An unbounded answer is a failed answer" belongs in any prompt whose schema contains an array of rich objects.
- **One phase, one job:** merge deduplicates, verify refutes, synthesize ranks. A merger also told to verify findings against the code becomes the largest input, the longest tool phase, and the longest emission in the run at once -- three stall risks stacked -- and it duplicates the adversarial phase that follows it.
- **A fan-out closes on its slowest unit, not its median.** When most units finish in minutes and one runs for an hour, the phase runs for an hour. Equalize unit sizes across a fan-out: one under-split unit forfeits the wall-clock benefit of splitting all the others.
- **Merge input grows with fan-out width, and nothing caps it.** Width is bounded by the concurrency limit; the reduce step's input is not, so N agents each emitting a few thousand tokens of findings hand the synthesizer N times that, and the barrier that made the fan-out safe makes the reduce step the largest single context in the run. Project each result down to the fields the merge actually needs, merge in groups and then merge the group outputs, and give every reduce step a deterministic identity fallback -- plain concatenation of its inputs -- so a dead merger degrades the answer instead of destroying the run.
- **Verification width is a product you do not directly choose: findings times verification concerns.** You pick the number of workers, but the data picks the number of findings, and five workers returning 200 findings spawn 600 verifiers at three concerns per finding. Bound data-derived fan-out explicitly -- cap it or filter before it, and log what the cap dropped -- and budget the run by expected finding count, never by worker count.
- **Name the operator's own traffic.** When the corpus under analysis contains traffic the operator generated while testing -- deploy probes, smoke checks -- name it in the shared context and exclude it explicitly, or every behavioral statistic the run produces is poisoned by the measurement itself.

## Resilience: Surviving Server Errors, Stalls, and Interruptions

Two different failure surfaces reach the script, and they behave differently. A terminal API error -- an HTTP 529 overloaded, a 502 -- surfaces as a null return from agent() after the harness exhausts its own retries, and parallel() and pipeline() convert a thrown thunk to null, so inside them a dead worker costs one item. A stalled agent is the other surface: when an agent emits no event for a few minutes, the harness aborts and retries it internally several times over, and once those attempts are spent the call THROWS -- a bare await agent() in the script body lets that exception escape and destroy the whole run, including every sibling result already paid for. An agent can even complete all of its work and still die returning the result when the connection drops at the last step, so a null does not mean the attempt was worthless, only that its output never arrived.

The stall is the more expensive surface because it is invisible while it happens: through the internal retries the run looks identical to a healthy long-running phase, no null ever reaches a retry helper because the agent never returns, and one badly scoped agent can consume an hour of wall clock and millions of tokens before the run fails or limps on. Design so the agent cannot stall -- bound its input, its output, and its exploration (see Sizing the Unit of Work above).

Grep the script for await agent( and await tryAgent( before launching; in practice the hits are exactly the reduce steps -- merge, cluster, synthesize, final judge -- the most expensive and latest agents in the run. A bare await agent( outside parallel() or pipeline() is a single point of total failure: wrap it in a retry helper that catches the throw. A wrapped call no longer throws but still returns null on final failure, so give its result the deterministic identity fallback from the sizing section.

Make every retry strictly cheaper than the last: reduce the scope, lower the tool-call budget, and say so in the retry note, because an identical retry of a task that failed on size fails the same way, and it multiplies with the harness's own internal attempts. Retry only what is transient: a deterministic rejection -- an invalid model-and-settings combination, a schema the endpoint refuses -- repeats exactly on every attempt, so change the failing parameter instead of retrying it. Keep the first attempt's prompt and opts byte-identical to the plain call so a resumed run replays it from cache, and give every later attempt a distinct label suffix and retry note so it gets its own cache identity. This stays resume-safe because the retry decision depends only on prior agent results, so control flow remains deterministic and cache-replayable.

Apply null discipline everywhere: filter(Boolean) after every parallel or pipeline harvest, and null-guard every property access on agent results (result?.field), because one dead agent must never crash the script and destroy all sibling work.

After every barrier, check quorum -- how many results arrived against how many you launched -- and when a required input is missing, re-run it or stop loudly, never continue silently on partial inputs. And notice that filter(Boolean) does not merely drop a dead voter -- it silently rewrites the decision rule: a majority-of-three threshold written as >= 2 becomes unanimity-of-two when one voter dies. Express thresholds relative to the surviving quorum, and carry the quorum into the result so a later reader knows how many voters actually spoke.

Accumulate partial results: push each completed item's output into a results array as it finishes so completed work survives any later failure, and design each phase's output as the accumulated survivors, never an all-or-nothing computation. Log every dropped item with its identity, because silent truncation is indistinguishable from completion and reintroduces agentic laziness at the script level.

```javascript
async function tryAgent(prompt, opts, attempts) {
  for (let att = 1; att <= attempts; att++) {
    const toolBudget = 16 >> (att - 1)                     // halves per attempt, so every retry is strictly cheaper
    let r = null
    try {
      r = await agent(
        att === 1 ? prompt : `${prompt}\n(Retry ${att} after a failure: reduce scope below the previous attempt -- deliver the core result in at most ${toolBudget} tool calls, keeping every field short.)`,
        att === 1 ? opts : { ...opts, label: `${opts.label}:retry${att}` },
      )
    } catch (err) {
      log(`${opts.label}: attempt ${att} threw: ${String(err).slice(0, 200)}`)
    }
    if (r) return r
    log(`${opts.label}: attempt ${att} of ${attempts} produced no result`)
  }
  return null
}

const results = []
const dropped = []
const raw = await parallel(items.map(it => () => tryAgent(promptFor(it), { label: `work:${it.id}` }, 3)))
raw.forEach((r, i) => (r ? results.push(r) : dropped.push(items[i].id)))
if (dropped.length) log(`quorum ${results.length}/${items.length}; dropped: ${dropped.join(', ')}`)

const rawVotes = await parallel(refutePrompts.map((p, i) => () => tryAgent(p, { label: `refute:${i}` }, 2)))
const votes = rawVotes.filter(Boolean)                     // three refuters launched; maybe fewer spoke
const refuted = votes.filter(v => v.refuted).length
const survives = votes.length > 0 && refuted < Math.ceil(votes.length / 2)
const verdict = { survives, quorum: votes.length, refuted }
```

Checkpoint at phase boundaries by keeping each phase a pure function of prior agent results, so after a crash in phase three a resume replays phases one and two from cache for free. For a phase expensive enough to hurt twice, additionally have each agent persist its own result durably as it completes -- a file at a known path, or a context-server entry -- so the phase is recoverable even where the replay cache is not.

Never kill a running workflow to inject new information. New knowledge almost always changes the cheap final phases -- the panel, the synthesis -- while killing re-runs the expensive gathering phase, so the cost and the benefit land on opposite ends. Let the run finish, then feed its output plus the new information to a short follow-up workflow.

Before interrupting or re-running anything, diagnose from the journal. The run summary's duration, agent count, and last log line reveal how far the run got, and the journal records one started event per attempt and one result event per completed call, both carrying the cache key and agent id: a key with several started events and no result is the stalling agent, its identity is the first user message of its per-agent transcript, and the transcript's tail shows how it died. One trap there: the harness records its own stall abort inside the transcript as [Request interrupted by user] -- nobody interrupted anything; that string is the stall signature, and reading it as an operator action closes the investigation on a false conclusion.

Recover by how far the run got. A run that died early is a resume: stop it, edit the persisted script file, and relaunch with that scriptPath plus resumeFromRunId, since the cache preserves what was already paid for. A run that died late is a harvest: the journal's result events carry each completed call's full structured return value keyed by cache key, so a few lines of code recover an entire finished phase and hand it to a fresh continuation workflow through args; where a completed call has no journal result, its per-agent transcript holds the value as the arguments of its last structured-output tool call -- skip transcripts without one (the harness's internal stall retries leave orphan transcripts) and dedupe by label. Use transcripts to diagnose how an agent died; use the journal to recover what it produced.

Budget a resume as mostly cached, never free. Replay is prefix-shaped: completion order inside a concurrent stage is nondeterministic, so the cache can stop matching at the first fan-out even under a byte-identical script, and a failed attempt is a permanent cache hole -- its successful retry lives under a different cache key and does not fill it, so every later resume re-pays for the failure. Confirm what actually replayed (a started event on a key that already carries a result is a call being paid for twice), and detect re-execution from new transcripts appearing, never from the progress counter, whose denominator differs from the original run's.

Protect cache identity when editing a script to fix a broken phase. A shared preamble embedded in every prompt is a cache-invalidation bomb: editing one word in it changes every key and re-buys everything already paid for, so keep the shared context and the per-agent instructions in separate constants, touch only the broken phase's prompts, and confirm before relaunching that the keys you did not mean to change are byte-identical. A late-phase prompt that interpolates upstream results is the same bomb in another shape -- its cache identity depends on the exact serialized text, including element order after a nondeterministic stage -- so canonicalize (sort by a stable key) before interpolating.

The determinism ban on the current-time and randomness built-ins protects this same replay cache; when a timestamp or seed is genuinely needed, compute it outside the script and pass it in via args.

Guard budget-scaled loops on budget.total being set, because it is not set when the user gave no cap, and inside long loops check budget.spent() to stop cleanly and emit accumulated results before the hard ceiling makes agent() throw.

## After Launch: The Harness Delivers Completion

The Workflow call returns as soon as the run starts, the runtime executes the script in the background while the session stays responsive, and when the run finishes the harness injects a completion notification carrying the result into the conversation on its own, waking the model for the next turn. Delivery is push, never pull: nothing the model does makes the report arrive sooner, and the same push contract covers every background primitive -- background subagents and backgrounded Bash commands equally notify on completion.

So after launching a run, either continue genuinely independent work or end the turn with a short status note that the workflow is running; an ended turn is the correct idle state, because the completion notification resumes the conversation automatically the moment the run finishes.

Never simulate waiting -- no Bash sleep timers, no watcher subagents dispatched to wait for the run, no status-polling loops. An artificial wait duplicates a delivery mechanism the harness already guarantees, and it cannot be timed because the finish time is unknowable in advance: a guess that runs long leaves the finished result undelivered until the timer expires, a guess that runs short just spawns another wait, and a user forced to break the timer with an interrupt hands the model an ambiguous stop signal easily misread as canceling the whole task. The fake wait burns tokens and delays the very result it claims to await.

Mid-run, reading the run's output or transcript files is for diagnosing a run that looks wrong, never a completion check -- and the working sign of wrong is a journal that has gone unwritten for far longer than one agent's work takes, which makes inspection at that point diagnosis, not polling. The /workflows view plus the task panel below the input box exist so the user can watch live progress -- point the user there when they ask how the run is going, and otherwise leave the run alone until the notification arrives.

## Operations: Budgets, Quick Workflows, Recurring Runs, and Prompting

Token budgets work from the request side: phrasing like "use a 10k token budget" sets the hard ceiling the harness enforces, so surface this phrasing to users who worry about cost, and scale agent count and depth to fit the cap rather than overrunning it.

Workflows are not only for large tasks: a quick workflow, such as a fast adversarial review of one assumption, buys the anti-bias structure at small cost, so offer it when a full harness would be overkill but one failure mode still threatens.

Pair repeatable workflows -- triage, research, verification -- with recurring-interval execution and set a hard completion goal, so scheduled runs neither drift nor stop early.

When authoring a workflow or shaping a user's request into one, name the pattern, the roles, the stop condition, the output schema and its length caps for any structured result, the exploration budget per role, and the model tier per role: the more the request mirrors this taxonomy, the closer the generated script lands to the intended architecture.

## Saving, Sharing, and Templates

Save a good workflow by pressing "s" in the workflow menu, and check saved scripts into the user-level workflows directory so they persist across sessions and machines.

Distribute a workflow by shipping its JavaScript script files inside a skill and referencing them from that skill's instructions.

Treat shipped scripts as templates, never as scripts to run verbatim, and say so in the shipping skill's prose: adapt file paths, rule lists, rubrics, and model choices to the task at hand before running, because verbatim reuse forfeits the tailor-made advantage that makes dynamic workflows outperform static harnesses, and frozen scripts rot as tasks drift.
