"""One packaged executable for editor RPC and explicit stdio MCP sessions."""

import sys


def main():
    if sys.argv[1:2] == ["--mcp"]:
        del sys.argv[1]
        from .mcp_server.server import main as serve
    else:
        from .rpc import main as serve
    serve()


if __name__ == "__main__":
    main()
