// One panel, two transports: MCP Apps host (iframe + postMessage) or standalone page (fetch + signed token).
import { App } from "@modelcontextprotocol/ext-apps";

const inHost = window.parent !== window;
const token = new URLSearchParams(location.search).get("t");
const $ = (s) => document.querySelector(s);
const show = (o) => { $("#result").textContent = JSON.stringify(o, null, 2); };

const transport = inHost ? hostTransport() : pageTransport();
$("#mode").textContent = inHost ? "MCP Apps host" : "standalone page";

function hostTransport() {
  const app = new App({ name: "sweep-panel", version: "0.1.0" });
  const ready = new Promise((res) => {
    app.ontoolresult = (p) => res(p.structuredContent ?? {});
  });
  app.connect();
  return {
    schema: () => ready.then((sc) => sc.schema),
    async submit(values) {
      const name = (await ready).submit_tool; // the opening tool names its own validator
      // submit_args carries what the opening tool fixed (e.g. measure_dir); values come from the form
      const r = await app.callServerTool({ name, arguments: { ...((await ready).submit_args ?? {}), values } });
      const out = r.structuredContent ?? JSON.parse(r.content?.[0]?.text ?? "{}");
      // Tell the model what the user did so the conversation can continue from it.
      await app.updateModelContext({ content: [{ type: "text", text: `Sweep panel submitted: ${JSON.stringify(out)}` }] }).catch(() => {});
      return out;
    },
  };
}

function pageTransport() {
  const q = `?t=${encodeURIComponent(token ?? "")}`;
  return {
    schema: () => fetch(`/panel/schema${q}`).then((r) => r.json()).then((j) => j.schema),
    submit: (values) => fetch(`/panel/submit${q}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ values }),
    }).then((r) => r.json()),
  };
}

function render(schema) {
  const form = $("#form");
  for (const [name, s] of Object.entries(schema)) {
    const row = document.createElement("fieldset");
    row.dataset.name = name;
    if (s.type === "choice") {
      row.innerHTML = `<legend>${s.label}</legend>` + s.choices.map((c) =>
        `<label><input type="checkbox" value="${c}" ${c === s.default ? "checked" : ""}> ${c}</label>`).join(" ");
    } else {
      const a = `type="number" step="any" min="${s.min}" max="${s.max}"`;
      row.innerHTML = `<legend>${s.label} (${s.units}, ${s.min}–${s.max})</legend>
        <label>from <input name="lo" ${a} value="${s.default}"></label>
        <label>to <input name="hi" ${a} value="${s.default}"></label>
        <label>steps <input name="steps" type="number" min="1" max="20" value="1"></label>`;
    }
    form.append(row);
  }
}

function collect() {
  const values = {};
  for (const row of document.querySelectorAll("fieldset")) {
    const checks = row.querySelectorAll("input[type=checkbox]");
    if (checks.length) { values[row.dataset.name] = [...checks].filter((c) => c.checked).map((c) => c.value); continue; }
    const n = (k) => Number(row.querySelector(`[name=${k}]`).value);
    values[row.dataset.name] = n("steps") > 1 ? [n("lo"), n("hi"), n("steps")] : n("lo");
  }
  return values;
}

transport.schema().then(render).catch((e) => show({ error: String(e) }));
$("#submit").addEventListener("click", async () => show(await transport.submit(collect())));
window.__collect = collect; window.__submit = (v) => transport.submit(v); // test hooks
