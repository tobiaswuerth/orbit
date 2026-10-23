"""`orbit serve`: the MCP tools agents call, the errors and instructions they read, and the server around them."""

import asyncio
import datetime
import json

import anyio
import pytest
import uvicorn
from mcp import Client
from starlette.testclient import TestClient

from orbit import __version__, server, vault
from orbit.crm import Crm
from orbit.errors import OrbitError

from .conftest import EXAMPLE
from .scenario import OWNER, STEPS, without_ids

TOOLS = [
    "resolve_entity",
    "get_entity_context",
    "search_entities",
    "list_entities",
    "log_interaction",
    "upsert_person",
    "upsert_organization",
    "upsert_topic",
    "link_entities",
    "link_document",
    "add_observation",
    "set_fields",
    "create_task",
    "update_task",
    "propose_review",
    "settle_review",
    "merge_entities",
    "rename_entity",
    "link_by_domain",
    "create_missing_references",
    "lint_vault",
]


def call(mcp, name, args=None):
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(name, args or {})

    return asyncio.run(go())


def data(result):
    """A tool's return value, whether MCP sent it as structured content or as JSON text."""
    assert not result.is_error, result.content
    content = result.structured_content
    if content is None:
        return json.loads(result.content[0].text)
    return content["result"] if set(content) == {"result"} else content


def tools(mcp):
    async def go():
        async with Client(mcp) as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    return asyncio.run(go())


@pytest.fixture
def mcp(crm):
    return server.build(crm)


def test_lists_the_tools(mcp):
    assert list(tools(mcp)) == TOOLS


def test_the_vault_it_serves_is_a_resource(crm):
    # So that a program finds the folder without reading it out of the instructions' prose.
    async def go():
        async with Client(server.build(crm, server.tool_names(["read"]))) as client:
            listed = (await client.list_resources()).resources
            return listed, await client.read_resource("orbit://vault")

    listed, read = asyncio.run(go())
    assert [(str(r.uri), r.mime_type) for r in listed] == [("orbit://vault", "application/json")]
    assert json.loads(read.contents[0].text) == {
        "vault": str(crm.vault.root),
        "version": __version__,
        "notes": {"interaction": 2, "organization": 1, "person": 4, "review": 1, "task": 2, "topic": 1},
    }


def test_every_tool_and_parameter_is_described(mcp):
    # Agents see a tool's schema, not its code: a parameter without a description is one they guess at, or miss.
    for tool in tools(mcp).values():
        assert len(tool.description) > 80, tool.name
        for name, schema in tool.input_schema["properties"].items():
            assert schema.get("description"), f"{tool.name}({name}) has no description"


def test_read_tools_are_marked_read_only(mcp):
    found = tools(mcp)
    reading = {"resolve_entity", "get_entity_context", "search_entities", "list_entities"}
    assert {name for name, tool in found.items() if tool.annotations.read_only_hint} == reading
    assert {name for name, tool in found.items() if tool.annotations.destructive_hint} == {"merge_entities"}
    assert not found["update_task"].annotations.idempotent_hint


def test_propose_review_says_what_each_answer_to_a_duplicate_does(mcp):
    description = tools(mcp)["propose_review"].description
    assert "yes merges them" in " ".join(description.split())
    assert "even where they were recorded as different" in " ".join(description.split())
    assert "no records the two as different" in " ".join(description.split())


READS = TOOLS[:4]
UPKEEP = ["merge_entities", "rename_entity", "link_by_domain", "create_missing_references", "lint_vault"]


def test_tools_come_in_groups_by_what_they_may_change():
    assert server.tool_names() == TOOLS
    assert server.tool_names(["read"]) == READS
    assert server.tool_names(["upkeep", "read"]) == READS + UPKEEP
    assert server.tool_names(["write"]) == [t for t in TOOLS if t not in READS + UPKEEP]
    assert server.tool_names(["read", "lint_vault", "read"]) == [*READS, "lint_vault"]
    with pytest.raises(OrbitError, match=r"--tools: 'delete' is neither a group \(read, write, upkeep\) nor a tool"):
        server.tool_names(["read", "delete"], "--tools")
    with pytest.raises(OrbitError, match=r"server\.tools: name at least one group \(read, write, upkeep\) or tool"):
        server.tool_names([], "server.tools")


def test_a_server_with_some_tools_says_which_it_leaves_out(crm):
    mcp = server.build(crm, server.tool_names(["read", "write"]))
    assert list(tools(mcp)) == [t for t in TOOLS if t not in UPKEEP]
    assert (
        "This connection offers only some of orbit's tools; the vault's owner left out merge_entities, rename_entity, "
        "link_by_domain, create_missing_references and lint_vault." in mcp.instructions
    )
    assert "left out" not in server.build(crm).instructions


def http_tools(app):
    """The tools each HTTP endpoint lists, after the handshake an MCP client makes."""
    hello = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    found = {}
    with TestClient(app, base_url="http://127.0.0.1:8775") as client:
        for path in server.ENDPOINTS:
            headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
            start = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": hello}
            headers |= {"Mcp-Session-Id": client.post(path, json=start, headers=headers).headers["mcp-session-id"]}
            client.post(path, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
            listed = client.post(path, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
            data = next(line for line in listed.text.splitlines() if line.startswith("data:"))
            found[path] = [t["name"] for t in json.loads(data.removeprefix("data:"))["result"]["tools"]]
    return found


def test_each_endpoint_offers_what_its_url_says_within_what_the_vault_allows(crm):
    writing = [t for t in TOOLS if t not in UPKEEP]
    assert http_tools(server.http_app(crm, "127.0.0.1")) == {"/mcp": TOOLS, "/mcp/write": writing, "/mcp/read": READS}
    limited = server.http_app(crm, "127.0.0.1", server.tool_names(["read", "lint_vault"]))
    assert http_tools(limited) == {"/mcp": [*READS, "lint_vault"], "/mcp/write": READS, "/mcp/read": READS}


def test_instructions_state_the_rules_and_the_vault(crm, mcp):
    text = mcp.instructions
    assert text.startswith("orbit keeps the personal CRM of Tobias, the vault's owner")
    assert "Resolve before you write" in text
    assert "Write only what a source states" in text
    assert f"The vault at {crm.vault.root} holds 4 person, 1 organization, 2 interaction" in text


def test_instructions_of_an_empty_vault(tmp_path, home):
    vault.init(tmp_path / "crm", now=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC))
    with Crm(tmp_path / "crm", home) as crm:
        assert "holds no notes yet" in server.build(crm).instructions
        crm.refresh()
        text = server.build(crm).instructions
        assert text.startswith("orbit keeps the personal CRM of Me, the vault's owner")
        (tmp_path / "crm" / "99_System" / "orbit.toml").write_text("", encoding="utf-8")
        crm.vault.reload()
        text = server.build(crm).instructions  # Me.md isn't known without orbit.toml's `me`
        assert text.startswith("orbit keeps the personal CRM of the vault's owner: Markdown notes")
        assert 'such as "the owner in chat,\n  2026-10-22"' in text


def test_read_tools(mcp):
    found = data(call(mcp, "resolve_entity", {"type": "person", "names": ["H. Müller"]}))
    assert found["candidates"][0]["name"] == "Hans Müller"
    context = data(call(mcp, "get_entity_context", {"id_or_name": "Hans Müller"}))
    assert context["fields"]["job_title"] == "Leiter Einkauf"
    assert data(call(mcp, "search_entities", {"query": "Mueller", "type": "person"}))[0]["name"] == "Hans Müller"
    listed = data(call(mcp, "list_entities", {"type": "task", "filters": {"status": "waiting"}}))
    assert listed["total"] == 1


def test_write_tools(mcp, crm):
    chat = "Tobias in chat, 2026-10-22"
    assert data(
        call(
            mcp,
            "link_document",
            {"entity": "Acme AG", "document": "https://x.example", "title": "Site", "source": chat},
        )
    )
    observed = {
        "entity": "Acme AG",
        "statement": "Grows",
        "evidence": "wir wachsen",
        "confidence": "high",
        "source": chat,
    }
    assert data(call(mcp, "add_observation", observed))["existing"] is False
    changed = data(
        call(
            mcp,
            "set_fields",
            {"entity": "Acme AG", "changes": {"industry": "Machines"}, "source": chat, "observed_at": "2026-10-22"},
        )
    )
    assert changed["applied"] == ["industry"]
    taken = {"entity": "Acme AG", "changes": {}, "remove": {"aliases": ["Acme"]}, "source": chat,
             "observed_at": "2026-10-22"}  # fmt: skip
    assert data(call(mcp, "set_fields", taken))["removed"] == []  # not among its aliases: nothing to take out
    task = "Anna Keller to follow up on the technical clarification"
    assert data(call(mcp, "update_task", {"task": task, "source": chat, "status": "done"}))["updated"] is True
    asked = {"kind": "question", "question": "Is Example Bank your bank?", "candidates": ["Me"], "evidence_for": [],
             "evidence_against": [], "source": chat}  # fmt: skip
    review = data(call(mcp, "propose_review", asked))["name"]
    refused = call(mcp, "settle_review", {"review": review, "done": "x", "source": chat})
    assert refused.is_error
    assert "not answered yet" in refused.content[0].text
    assert data(call(mcp, "lint_vault"))["counts"] == {"error": 0, "warning": 0}
    renamed = data(call(mcp, "rename_entity", {"id_or_name": "Hans", "new_name": "Hans B", "source": chat}))
    assert renamed["name"] == "Hans B"
    merged = data(call(mcp, "merge_entities", {"keep": "Hans Müller", "drop": "Hans B", "source": chat}))
    assert merged["id"] == "per_01M4WNN540CGMAHYXV1R90AA5V"
    assert data(call(mcp, "create_missing_references", {"dry_run": True}))["created"] == []
    assert data(call(mcp, "link_by_domain", {"dry_run": True}))["linked"] == []


def test_several_links_and_addresses_through_mcp(mcp):
    links = [
        {"relation": "to", "to": "anna.keller@acme-ag.example"},
        {"relation": "topics", "to": "Wartungsvertrag 2027"},
    ]
    arguments = {"entity": "2026-10-18 Email – Segelwochenende Bodensee", "source": "Tobias in chat", "links": links}
    result = data(call(mcp, "link_entities", arguments))
    assert [(link["to"], link["linked"]) for link in result["links"]] == [
        ("[[Anna Keller]]", True),
        ("[[Wartungsvertrag 2027]]", True),
    ]


def test_errors_reach_the_agent_with_what_to_do(mcp):
    result = call(
        mcp,
        "upsert_person",
        {
            "match": "new",
            "fields": {"name": "H", "emails": ["hans.mueller@acme-ag.example"]},
            "source": "x",
            "resolution_reason": "x",
        },
    )
    assert result.is_error
    assert 'call upsert_person with match "per_01M4WNN540CGMAHYXV1R90AA5V"' in result.content[0].text


def test_unexpected_errors_name_their_type(mcp, monkeypatch, caplog):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(server.reads, "search", broken)
    result = call(mcp, "search_entities", {"query": "x"})
    assert result.is_error
    assert result.content[0].text.endswith("search_entities: RuntimeError: boom")
    assert "tool failed" in caplog.text


def test_an_agent_rebuilds_the_example_vault_through_mcp(tmp_path, home):
    root = tmp_path / "crm"
    vault.init(root, *OWNER, now=datetime.datetime.fromisoformat("2026-10-01T12:00:00+02:00"))
    with Crm(root, home) as crm:
        crm.refresh()
        mcp = server.build(crm)
        for day, tool, arguments in STEPS:
            crm.now = lambda day=day: datetime.datetime.fromisoformat(f"{day}T12:00:00+02:00")
            data(call(mcp, tool, arguments))
    for path in EXAMPLE.rglob("*.md"):
        rel = path.relative_to(EXAMPLE)
        assert without_ids((root / rel).read_text(encoding="utf-8")) == without_ids(path.read_text(encoding="utf-8"))


def test_serve_over_http(example, home, monkeypatch, capsys):
    served = []

    async def fake_http(mcp, host, port):
        served.append((host, port))

    monkeypatch.setattr(server, "_serve_http", fake_http)
    server.serve(example)
    assert served == [("127.0.0.1", 8775)]
    err = capsys.readouterr().err
    assert "index up to date (11 added, 0 changed, 0 removed)" in err
    assert "orbit MCP server on http://127.0.0.1:8775/mcp" in err
    server.serve(example, host="::", port=9000)
    assert served[-1] == ("::", 9000)
    err = capsys.readouterr().err
    assert "on http://[::]:9000/mcp" in err
    assert "warning: listening on ::, so anyone who reaches port 9000 can read and change the CRM" in err
    assert "/mcp/write: no merges, renames or lint; /mcp/read: reading only" in err


def test_serve_offers_the_tools_orbit_toml_or_the_command_allows(example, home, monkeypatch):
    allowed = []
    monkeypatch.setattr(server, "http_app", lambda crm, host, tools: allowed.append(tools))
    monkeypatch.setattr(server, "_serve_http", lambda app, host, port: anyio.sleep(0))
    config = example / "99_System" / "orbit.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("port = 8775", 'port = 8775\ntools = ["read"]'), encoding="utf-8")
    server.serve(example)
    server.serve(example, tools=["read", "write"])
    assert allowed == [READS, [t for t in TOOLS if t not in UPKEEP]]
    config.write_text(config.read_text(encoding="utf-8").replace('"read"', '"everything"'), "utf-8")
    with pytest.raises(OrbitError, match=r"orbit\.toml: server\.tools: 'everything' is neither a group"):
        server.serve(example)


def test_serve_over_stdio(example, home, monkeypatch, capsys):
    ran = []

    async def fake_stdio(self):
        ran.append([t.name for t in await self.list_tools()])

    monkeypatch.setattr(server.MCPServer, "run_stdio_async", fake_stdio)
    server.serve(example, stdio=True)
    server.serve(example, stdio=True, tools=["read"])
    assert ran == [TOOLS, READS]
    assert "MCP server on" not in capsys.readouterr().err


def test_the_http_app_answers_mcp(crm):
    app = server.build(crm).streamable_http_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8775") as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    assert "orbit" in response.text


def test_http_is_served_by_uvicorn_with_a_time_limit_on_shutdown(crm, monkeypatch):
    configs = []

    async def fake_serve(self):
        configs.append(self.config)

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)
    asyncio.run(server._serve_http(server.build(crm), "127.0.0.1", 8775))
    (config,) = configs
    assert (config.host, config.port, config.timeout_graceful_shutdown) == ("127.0.0.1", 8775, server.SHUTDOWN_SECONDS)


def test_the_http_app_refuses_requests_for_other_hosts(crm):
    # DNS rebinding: a web page under another domain must not reach a server bound to this machine.
    app = server.build(crm).streamable_http_app(host="127.0.0.1")
    with TestClient(app, base_url="http://evil.example") as client:
        response = client.post("/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 421
    with TestClient(server.http_app(crm, "127.0.0.1"), base_url="http://evil.example") as client:
        for path in server.ENDPOINTS:
            response = client.post(path, json={}, headers={"Accept": "application/json, text/event-stream"})
            assert response.status_code == 421, path
