# sweep_panel

An MCP Apps panel for setting up a parametric sweep of one measure's numeric
arguments. It comes from the generative-UI spike in discussion #273.

| Tool | What it does |
|---|---|
| `open_measure_panel(measure_dir)` | Returns the panel schema. MCP Apps hosts render `ui://sweep/panel.html` inline. Over HTTP the result also has `fallback.panel_url`, a signed, single-submit browser link. |
| `submit_measure_sweep(measure_dir, values)` | Checks the values on the server and returns `next`, the `openstudio_analysis_add_measure_to_osa_json` arguments. The panel calls it through the host. The model can call it too. |
| `get_panel_result(link_id)` | Reads what was submitted on a browser link (HTTP only). |

## Where the limits come from

Only numeric arguments with a known range get a panel field.

The range is read from measure.xml (`<min_value>`, `<max_value>`, `<units>`). Where measure.xml doesn't declare one, it comes from `../analysis/measure_bounds/<measure.xml name>.json`. Almost no measure declares its own range.

The same limits gate `openstudio_analysis_add_measure_to_osa_json` (`analysis/measure_bounds.py`), so a value outside them is refused whether it comes from the panel or straight from the model.

To make another measure sweepable, add a bounds file for it.

## Transports

- **stdio (local, Docker):** inline panel only. There is no web server, so there is no browser link. A CLI client gets text.
- **HTTP (hosted):** inline panel, plus the browser link at `/panel?t=…`. The link reuses `file_transfer/signing.py` with op `"p"`. Its results are stored under the caller's run root. The first valid submit closes the link. The `?t=` query is redacted from the access log.

## Rebuilding panel.html

`panel.html` is built from `web/panel.src.html` and `web/panel.js`, with `@modelcontextprotocol/ext-apps` 2.0.4 bundled in.

```bash
cd mcp_server/skills/sweep_panel/web
npm install --no-save @modelcontextprotocol/ext-apps@2.0.4 esbuild@0.28.2
npx esbuild panel.js --bundle --minify --format=iife --outfile=bundle.js
python3 -c "s=open('panel.src.html').read(); open('../panel.html','w').write(s.replace('/*BUNDLE*/', open('bundle.js').read()))"
rm -rf bundle.js node_modules
```
