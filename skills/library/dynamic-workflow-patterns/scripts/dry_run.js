// Dry run of a Workflow script: runs the script body against stub agents, so its control flow
// -- which agent() calls run, in what order, what a null result, a throw, a retry, or a dropped
// pipeline item does to the rest of the run, which side of a gate an answer sends an item down,
// and which unawaited call rejects with no handler -- shows before a launch spends real agents on
// it. A stub answers from its call's JSON schema, or with the value an answer flag gives it, so
// the dry run says nothing about whether a prompt, a schema, or a unit's size holds up against a
// real agent. Run it without arguments for its usage.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const USAGE = `usage: node dry_run.js <script-file> [options]
  --args <json>                   the value the script reads as args
  --args-file <path>              the same value, read from a JSON file
  --lens-model <id>               admit a declared lens model besides the 1M identifiers (repeatable)
  --null <label-prefix>           agent() calls whose label starts with the prefix return null (repeatable)
  --throw <label-prefix>          agent() calls whose label starts with the prefix throw (repeatable)
  --null-once <prefix>            only the first matching call returns null
  --throw-once <prefix>           only the first matching call throws
  --answer <label-prefix> <json>  agent() calls whose label starts with the prefix answer with the value (repeatable)
  --answer-once <prefix> <json>   only the first matching call answers with the value
  --budget <tokens>               set budget.total; every stub call spends --tokens-per-call of it
  --tokens-per-call <n>           what one stub call adds to budget.spent() (default 10000)
A call without a schema returns an answer that is a JSON string as its agent's text and refuses
any other answer; a call with a schema returns its stub with the answer's keys laid over it, and
refuses an answer that is not an object or names a key its schema does not declare. When several
failure flags match one call's label, the first one given that still has a failure left decides;
a matching failure flag decides before any answer flag, and among several matching answer flags
the first one given that still has a use left decides. A call with no label is labeled agent-<n>,
n counting calls from 1.
The report is one JSON document on stdout; the exit code is 0 for a run with no violation
and no uncaught script error, 1 otherwise, and 2 for a usage error.
`;

const AGENT_CAP = 1000;
const ITEM_CAP = 4096;
const LONG_CONTEXT_SUFFIX = "[1m]";
const META_EXPORT = /^(\s*)export\s+const\s+meta\s*=/m;

// The Workflow runtime refuses these three because a resumed run must replay the same calls.
const PRELUDE = `(() => {
  const unavailable = (what) => new Error(
    what + " is unavailable in a Workflow script, because it would break resume; pass timestamps in "
      + "through args, and vary a prompt or label by index instead of drawing a random number");
  class WorkflowDate extends Date {
    constructor(...values) {
      if (values.length === 0) throw unavailable("new Date() without arguments");
      super(...values);
    }
    static now() {
      throw unavailable("Date.now()");
    }
  }
  globalThis.Date = WorkflowDate;
  Math.random = () => {
    throw unavailable("Math.random()");
  };
})();`;

function describe(error) {
  return error !== null && typeof error === "object" && typeof error.message === "string" ? error.message : String(error);
}

function parseJson(text, flag) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${flag} is not valid JSON: ${describe(error)}`);
  }
}

function parseCount(text, flag) {
  const value = Number(text);
  if (!Number.isInteger(value) || value < 0) throw new Error(`${flag} takes a whole number, not ${text}`);
  return value;
}

function parseOptions(argv) {
  const options = {
    script: null,
    args: undefined,
    lensModels: [],
    failures: [],
    answers: [],
    budget: null,
    tokensPerCall: 10000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = () => {
      index += 1;
      if (index >= argv.length) throw new Error(`${flag} needs a value`);
      return argv[index];
    };
    switch (flag) {
      case "--args":
        options.args = parseJson(value(), flag);
        break;
      case "--args-file":
        options.args = parseJson(fs.readFileSync(value(), "utf8"), flag);
        break;
      case "--lens-model":
        options.lensModels.push(value());
        break;
      case "--null":
      case "--null-once":
      case "--throw":
      case "--throw-once":
        options.failures.push({
          prefix: value(),
          mode: flag.startsWith("--null") ? "null" : "throw",
          remaining: flag.endsWith("-once") ? 1 : Infinity,
        });
        break;
      case "--answer":
      case "--answer-once": {
        const prefix = value();
        options.answers.push({
          prefix,
          value: parseJson(value(), flag),
          remaining: flag.endsWith("-once") ? 1 : Infinity,
        });
        break;
      }
      case "--budget":
        options.budget = parseCount(value(), flag);
        break;
      case "--tokens-per-call":
        options.tokensPerCall = parseCount(value(), flag);
        break;
      default:
        if (flag.startsWith("--") || options.script !== null) throw new Error(`unexpected argument ${flag}`);
        options.script = flag;
    }
  }
  if (options.script === null) throw new Error("name the workflow script file to dry-run");
  return options;
}

function checkSchema(schema) {
  const rooted = schema !== null && typeof schema === "object" && schema.type === "object";
  if (!rooted || schema.properties === null || typeof schema.properties !== "object") {
    return "its schema needs {type: 'object', properties: {...}} at the root";
  }
  const undefinedKeys = (schema.required ?? []).filter((key) => !(key in schema.properties));
  return undefinedKeys.length > 0 ? `its schema requires undefined properties: ${undefinedKeys.join(", ")}` : null;
}

function schemaType(schema) {
  if (Array.isArray(schema.type)) return schema.type.find((type) => type !== "null") ?? "null";
  if (schema.type !== undefined) return schema.type;
  if (schema.properties !== undefined) return "object";
  return schema.items !== undefined ? "array" : "string";
}

// A stub answer: every required property filled with a value of its type, arrays with one or
// two items, an enum's first value, and the property path as each string.
function sample(schema, where) {
  if (schema === null || typeof schema !== "object") return where;
  if ("const" in schema) return schema.const;
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0];
  const branches = schema.anyOf ?? schema.oneOf;
  if (Array.isArray(branches) && branches.length > 0) {
    return sample(branches.find((branch) => branch?.type !== "null") ?? branches[0], where);
  }
  switch (schemaType(schema)) {
    case "object": {
      const value = {};
      for (const key of schema.required ?? []) value[key] = sample(schema.properties?.[key], `${where}.${key}`);
      return value;
    }
    case "array": {
      const count = Math.max(schema.minItems ?? 1, Math.min(2, schema.maxItems ?? 2));
      return Array.from({ length: count }, (_, index) => sample(schema.items, `${where}[${index}]`));
    }
    case "integer":
    case "number":
      return schema.minimum ?? 1;
    case "boolean":
      return true;
    case "null":
      return null;
    default:
      return where;
  }
}

function createRuntime(options) {
  const trace = [];
  const violations = [];
  let calls = 0;
  let spent = 0;
  let currentPhase = null;
  // The top-level script's context, whose meta the report shows even when the script throws after declaring it.
  let topContext = null;
  let scriptFile = null;

  const report = (result, error) => ({
    script: scriptFile,
    meta: topContext?.__workflowMeta ?? null,
    agentCalls: calls,
    trace,
    result,
    error,
    violations,
  });

  const budget = {
    total: options.budget,
    spent: () => spent,
    remaining: () => (options.budget === null ? Infinity : Math.max(0, options.budget - spent)),
  };

  // A rejection Node reported as unhandled counts until a handler attaches to it later.
  const unhandled = new Map();
  process.on("unhandledRejection", (reason, promise) => {
    unhandled.set(promise, describe(reason));
    trace.push({ kind: "unawaited-rejection", reason: describe(reason) });
  });
  process.on("rejectionHandled", (promise) => unhandled.delete(promise));

  function refuse(call, message) {
    call.outcome = "refused";
    violations.push(message);
    return new Error(`dry run refused ${call.label}: ${message}`);
  }

  // The first flag given whose prefix starts the label and that still has a use left decides the call and spends a use.
  function takeFlag(entries, label) {
    const entry = entries.find((candidate) => candidate.remaining > 0 && label.startsWith(candidate.prefix));
    if (entry !== undefined) entry.remaining -= 1;
    return entry;
  }

  // Why a call with a schema could never return the answer, or null when it could.
  function answerProblem(schema, answer) {
    if (answer === null || typeof answer !== "object" || Array.isArray(answer)) {
      return `the answer given for it is ${JSON.stringify(answer)}, but a call with a schema returns an object`;
    }
    const undeclared = Object.keys(answer).filter((key) => !Object.hasOwn(schema.properties, key));
    return undeclared.length > 0 ? `its schema does not declare the answer's keys: ${undeclared.join(", ")}` : null;
  }

  // Why a call without a schema, which returns its agent's text, could never return the answer, or null when it could.
  function textAnswerProblem(answer) {
    return typeof answer === "string"
      ? null
      : `the answer given for it is ${JSON.stringify(answer)}, but a call without a schema returns its agent's text`;
  }

  async function agent(prompt, opts = {}) {
    calls += 1;
    const label = typeof opts.label === "string" && opts.label !== "" ? opts.label : `agent-${calls}`;
    const call = {
      kind: "agent",
      call: calls,
      label,
      model: opts.model ?? null,
      effort: opts.effort ?? null,
      phase: opts.phase ?? currentPhase,
      schema: opts.schema !== undefined,
      isolation: opts.isolation ?? null,
      outcome: "pending",
    };
    trace.push(call);
    if (calls > AGENT_CAP) {
      violations.push(`the script made more than ${AGENT_CAP} agent() calls, the runtime's cap for one workflow`);
      process.stdout.write(`${JSON.stringify(report(null, "stopped at the agent cap"), null, 2)}\n`);
      process.exit(1);
    }
    const { model } = opts;
    if (typeof model !== "string" || model === "") throw refuse(call, `${label} names no model`);
    if (!model.endsWith(LONG_CONTEXT_SUFFIX) && !options.lensModels.includes(model)) {
      throw refuse(call, `${label} names ${model}, which is neither a 1M identifier nor a lens declared with --lens-model`);
    }
    const schemaProblem = opts.schema === undefined ? null : checkSchema(opts.schema);
    if (schemaProblem !== null) throw refuse(call, `${label}: ${schemaProblem}`);
    if (budget.total !== null && spent >= budget.total) {
      call.outcome = "threw";
      throw new Error(`the token budget of ${budget.total} is spent`);
    }
    spent += options.tokensPerCall;
    const failure = takeFlag(options.failures, label);
    if (failure?.mode === "null") {
      call.outcome = "null";
      return null;
    }
    if (failure?.mode === "throw") {
      call.outcome = "threw";
      throw new Error(`injected failure of ${label}`);
    }
    const answer = takeFlag(options.answers, label);
    if (answer !== undefined) {
      const answerIssue = opts.schema === undefined ? textAnswerProblem(answer.value) : answerProblem(opts.schema, answer.value);
      if (answerIssue !== null) throw refuse(call, `${label}: ${answerIssue}`);
      call.outcome = "answered";
      const given = structuredClone(answer.value);
      return opts.schema === undefined ? given : { ...sample(opts.schema, label), ...given };
    }
    call.outcome = opts.schema === undefined ? "text" : "object";
    return opts.schema === undefined ? `${label}: dry-run answer` : sample(opts.schema, label);
  }

  function checkItemCount(name, items) {
    if (Array.isArray(items) && items.length > ITEM_CAP) throw new Error(`${name}() takes at most ${ITEM_CAP} items`);
  }

  async function parallel(thunks) {
    checkItemCount("parallel", thunks);
    return Promise.all(
      thunks.map(async (thunk, index) => {
        try {
          return await thunk();
        } catch (error) {
          trace.push({ kind: "null-result", where: `parallel item ${index}`, reason: describe(error) });
          return null;
        }
      }),
    );
  }

  // A stage that throws or resolves to null drops its item to null and skips the item's later stages.
  async function pipeline(items, ...stages) {
    checkItemCount("pipeline", items);
    return Promise.all(
      items.map(async (item, index) => {
        let value = item;
        for (const [position, stage] of stages.entries()) {
          const where = `pipeline item ${index}, stage ${position + 1}`;
          try {
            value = await stage(value, item, index);
          } catch (error) {
            trace.push({ kind: "dropped", where, reason: describe(error) });
            return null;
          }
          if (value === null) {
            trace.push({ kind: "dropped", where, reason: "the stage resolved to null" });
            return null;
          }
        }
        return value;
      }),
    );
  }

  function phase(title) {
    currentPhase = title;
    trace.push({ kind: "phase", title });
  }

  function log(message) {
    trace.push({ kind: "log", message: String(message) });
  }

  function workflowFor(file, depth) {
    return async (nameOrRef, childArgs) => {
      if (depth > 0) throw new Error("workflow() inside a child workflow throws: nesting is one level only");
      if (nameOrRef !== null && typeof nameOrRef === "object" && typeof nameOrRef.scriptPath === "string") {
        const child = path.resolve(path.dirname(file), nameOrRef.scriptPath);
        trace.push({ kind: "workflow", script: child });
        return runScript(child, childArgs, depth + 1);
      }
      trace.push({ kind: "workflow", name: String(nameOrRef), note: "a named workflow is not run in a dry run; it returned null" });
      return null;
    };
  }

  async function runScript(file, args, depth) {
    const source = fs.readFileSync(file, "utf8");
    if (!META_EXPORT.test(source)) violations.push(`${path.basename(file)} does not declare export const meta`);
    const body = source.replace(META_EXPORT, "$1const meta = globalThis.__workflowMeta =");
    const context = vm.createContext({ setTimeout, clearTimeout });
    if (depth === 0) topContext = context;
    vm.runInContext(PRELUDE, context);
    const wrapped = `(async function (agent, parallel, pipeline, phase, log, budget, workflow, args) {\n${body}\n})`;
    const main = vm.runInContext(wrapped, context, { filename: file, lineOffset: -1 });
    return main(agent, parallel, pipeline, phase, log, budget, workflowFor(file, depth), args);
  }

  async function run(file, args) {
    scriptFile = file;
    let result = null;
    let error = null;
    try {
      const value = await runScript(file, args, 0);
      result = value === undefined ? null : value;
    } catch (thrown) {
      const frame = String(thrown?.stack ?? "")
        .split("\n")
        .find((line) => line.includes(file));
      error = frame === undefined ? describe(thrown) : `${describe(thrown)} (${frame.trim()})`;
    }
    // Node reports a rejection nothing handled only after the current microtasks drain, so wait one turn for it.
    await new Promise((resolve) => setImmediate(resolve));
    for (const reason of unhandled.values()) violations.push(`an unawaited agent() call rejected with no handler: ${reason}`);
    return report(result, error);
  }

  return { run };
}

async function main() {
  let options;
  try {
    options = parseOptions(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`dry_run: ${describe(error)}\n${USAGE}`);
    process.exitCode = 2;
    return;
  }
  const report = await createRuntime(options).run(path.resolve(options.script), options.args);
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  process.exitCode = report.violations.length > 0 || report.error !== null ? 1 : 0;
}

main();
