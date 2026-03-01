import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.markdown import Markdown
from agent.core import TutorAgent

console = Console()
agent = TutorAgent()

console.print("[bold green]🌍 LangTutor[/] — Your personal language tutor")
console.print("Type 'quit' to exit\n")

while True:
    msg = console.input("[bold cyan]You:[/] ")
    if msg.strip().lower() in ("quit", "exit", "q"):
        break
    reply = agent.chat(msg)
    console.print()
    console.print(Markdown(reply))
    console.print()
