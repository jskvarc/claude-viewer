"""Entry point: python main.py [--host HOST] [--port PORT]"""
import argparse

from nicegui import ui

from claude_viewer.app import register_pages


def main() -> None:
    parser = argparse.ArgumentParser(description='Browse and search Claude Code session history.')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8080, help='port (default: 8080)')
    parser.add_argument('--show', action='store_true', help='open the browser automatically')
    args = parser.parse_args()
    register_pages()
    ui.run(host=args.host, port=args.port, title='Claude Code Viewer',
           reload=False, show=args.show)


if __name__ in {'__main__', '__mp_main__'}:
    main()
