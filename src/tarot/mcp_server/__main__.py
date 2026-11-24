import argparse

from tarot.mcp_server.server import build_server

p = argparse.ArgumentParser(prog="python -m tarot.mcp_server")
p.add_argument("--http", action="store_true", help="streamable HTTP at /mcp instead of stdio")
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=8765)
args = p.parse_args()
server = build_server()
if args.http:
    server.run("streamable-http", host=args.host, port=args.port, stateless_http=True)
else:
    server.run("stdio")
