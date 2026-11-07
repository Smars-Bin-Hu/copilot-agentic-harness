# Tool packs and MCP servers

Both give the agent a fixed set of calls, so it does not build commands by hand. They differ in three places. Those three are why the harness has tool packs.

## 1. Whether the company can use it

Many companies switch MCP off by policy. A tool pack reaches the tool through a plain program in its `bin/` (for example `ado`). The program runs in the terminal the editor already allows.

MCP is optional in the protocol. A pack may also carry `mcp.json`, and a company that allows MCP uses it. Both ways go through the same gate rules.

## 2. Who holds "a write waits for the person"

An MCP server does not. With a ticket server's MCP tools, `update_work_item` writes at once. The only brake is the editor's "confirm every tool call". It cannot tell a read from a write, or say whether the task is linked to that ticket.

A tool pack's connection type says:

- which call is a read, a write or a job;
- which item a write changes (`item`);
- what the held card shows in words (`say`, `body`, `show`).

This is where the harness's own abilities (tasks, gate, approvals, linked items) meet the tool. MCP tool calls go through the gate too, and a write asks. But the server gives none of this information. The pack's type does.

## 3. Skills are needed either way

A server says what can be called. It does not say when, in which order, or how the company does it. The SOP skills of a pack (`<prefix>-<pack>-<name>`) are the half MCP never had.

## In one line

A tool pack is the tool list in a form the company can run, plus the gate's marks for reads and writes, plus the SOP skills. If MCP is allowed one day, a pack adds `mcp.json` beside `bin/`. Its types, rules and skills stay.

## The cost

A pack's own program follows the tool's public API. The pack's author must keep it up to date. An official MCP server is kept by its vendor. So the factory packs cover systems with stable, public interfaces, and a pack is checked once against the real server at the company.
