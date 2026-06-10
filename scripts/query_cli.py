#!/usr/bin/env python3
"""Interactive CLI for querying the RAG knowledge base."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()
API_URL = os.getenv("RAG_API_URL", "http://localhost:8100")

def check_api() -> bool:
 try:
 resp = httpx.get(f"{API_URL}/health", timeout=5)
 return resp.status_code == 200
 except Exception:
 return False

def query(question: str, top_k: int = 5) -> dict | None:
 try:
 resp = httpx.post(
 f"{API_URL}/query",
 json={"question": question, "top_k": top_k},
 timeout=120,
 )
 resp.raise_for_status()
 return resp.json()
 except httpx.HTTPStatusError as exc:
 console.print(f"[red]API error {exc.response.status_code}: {exc.response.text}[/red]")
 return None
 except Exception as exc:
 console.print(f"[red]Request failed: {exc}[/red]")
 return None

def display_response(data: dict) -> None:
 # Answer panel
 if not data.get("ollama_available"):
 console.print(Panel(
 "[yellow] Ollama not available — showing retrieved context only[/yellow]",
 border_style="yellow",
 ))

 console.print(Panel(
 Markdown(data["answer"]),
 title=f"[bold green]Answer[/bold green] [dim]({data['elapsed_ms']}ms · {data['model']})[/dim]",
 border_style="green",
 ))

 # Sources table
 if data.get("sources"):
 table = Table(title="Sources", show_lines=True)
 table.add_column("Score", style="cyan", width=7)
 table.add_column("Document", style="blue")
 table.add_column("Excerpt", style="dim")
 for src in data["sources"]:
 table.add_row(
 f"{src['relevance_score']:.3f}",
 src["object_name"],
 src["excerpt"][:120] + "..." if len(src["excerpt"]) > 120 else src["excerpt"],
 )
 console.print(table)

def main():
 console.print(Panel(
 "[bold cyan]Cloudflare Docs RAG[/bold cyan]\n"
 "Ask questions about Cloudflare Workers, R2, D1, KV, Pages and more.\n"
 "Type [bold]quit[/bold] or [bold]exit[/bold] to stop.",
 border_style="cyan",
 ))

 if not check_api():
 console.print(f"[red] Cannot reach API at {API_URL}[/red]")
 console.print(" Make sure services are running: [bold]make up[/bold]")
 sys.exit(1)

 console.print(f"[green] Connected to RAG API at {API_URL}[/green]\n")

 while True:
 try:
 question = Prompt.ask("[bold]Ask[/bold]").strip()
 except (KeyboardInterrupt, EOFError):
 console.print("\n[dim]Bye![/dim]")
 break

 if not question:
 continue
 if question.lower() in ("quit", "exit", "q"):
 console.print("[dim]Bye![/dim]")
 break

 with console.status("[dim]Thinking...[/dim]"):
 data = query(question)

 if data:
 display_response(data)
 console.print()

if __name__ == "__main__":
 main()
