import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.markdown import Markdown
from agent.core import TutorAgent

console = Console()

BANNER = r"""[bold green]
  ╔╦╗╦╔═╗╔╦╗╦═╗╔═╗╦    ╦  ╔═╗╔═╗╦═╗╔╗╔
  ║║║║╚═╗ ║ ╠╦╝╠═╣║    ║  ║╣ ╠═╣╠╦╝║║║
  ╩ ╩╩╚═╝ ╩ ╩╚═╩ ╩╩═╝  ╩═╝╚═╝╩ ╩╩╚═╝╚╝
[/]"""

console.print(BANNER)
console.print("  [dim]Your personal language tutor · Type 'quit' to exit[/]\n")

agent = TutorAgent()

# Agent speaks first
opening = agent.chat("__session_start__")
console.print(Markdown(opening))
console.print()

while True:
    msg = console.input("[bold cyan]You:[/] ")
    if msg.strip().lower() in ("quit", "exit", "q"):
        break
    reply = agent.chat(msg)
    console.print()
    console.print(Markdown(reply))
    console.print()
