# Install openstudio-mcp for my MCP host

Install the openstudio-mcp server (https://github.com/NatLabRockies/openstudio-mcp)
as a local stdio MCP server and connect it to my MCP host.

Steps 3, 5 and 6 need answers from me. End your turn with the question each time.
If you have no way to ask me, stop there and list what you need: my answers come
before any folder is created or any config is changed.

1. Read the "Quick start (local)" section of
   https://raw.githubusercontent.com/NatLabRockies/openstudio-mcp/develop/README.md
   (or README.md if you are inside a clone of the repo). It is the source of truth
   for the docker args, mounts and config snippets; these instructions only add the order
   of work and the points where you wait for me.
2. Check my OS and CPU architecture, then run `docker info`. If Docker is missing or
   the daemon isn't running, give me the Docker Desktop download link or tell me to
   start it, then wait for me to say it's ready. Installing Docker is my job.
3. Ask me which MCP host to connect (Claude Desktop, Claude Code, Codex, VS Code,
   Cursor, other) and find where that host keeps its MCP server config.
4. Get the latest release tag from the `tag_name` field of
   https://api.github.com/repos/NatLabRockies/openstudio-mcp/releases/latest
   (fetch it with curl or gh; a web search can return an old cached page), then
   pull nrel/openstudio-mcp:<that tag>. Use that exact tag (no -beta, -amd64 or -arm64
   suffix) even if the README shows an older one. A new release's image can take
   about 20 minutes to reach Docker Hub: if the tag is not found, wait a few minutes
   and retry, or ask me. Clone and build from source only
   if I ask for unreleased changes; the README says which Dockerfile fits my CPU.
5. Suggest three folders on my machine for models (/inputs, read-only), simulation
   output (/runs) and measures (/measures). Wait for me to confirm or change them,
   then create them. Use absolute paths, with forward slashes on Windows.
6. Register a server named "openstudio-mcp" with my host, using the README's
   `docker run` args with my three folders and the image you pulled in place of
   `openstudio-mcp:dev`. If a server with that name already exists, tell me only its
   name, type, and URL or command (print no headers, env values or tokens), and
   ask whether to replace it or use another name.
   - Claude Code: use `claude mcp add --scope user openstudio-mcp -- docker run ...`.
   - Hosts with a config file: copy the file to a timestamped backup first, then
     merge the new entry in and keep every existing server and setting as it was.
     Use the README's JSON or TOML snippet, adapted to that host's format.
7. Verify before I restart anything: `docker image inspect <image>` succeeds, and
   the exact command you registered starts the server. To test the start, send one
   MCP `initialize` JSON-RPC request on stdin, keep stdin open until the reply
   arrives (allow up to 2 minutes) and expect it to name the server. If you can't
   capture a reply, a container that starts with no Docker error counts as a pass;
   tell me which check you used. On a Docker error (image not found, bad mount
   path), fix the registration and check again.
8. Tell me to restart my host and try: "Call get_server_status and create an
   example model."
9. Report the image tag, the three folder paths, the config file or command you
   changed, and the backup location.
