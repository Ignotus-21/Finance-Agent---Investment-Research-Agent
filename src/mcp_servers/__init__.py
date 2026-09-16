"""Model Context Protocol servers exposing IRA capabilities to MCP clients.

Currently one server: :mod:`src.mcp_servers.sec_edgar_server`, which fronts
SEC EDGAR retrieval. It is launched as a stdio subprocess by the ADK agent.

Nothing is re-exported here on purpose. Importing a server module builds its
tool registry as a side effect, and that should only happen in the process
that actually intends to serve.
"""
