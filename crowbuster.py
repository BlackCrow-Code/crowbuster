import os
import time
import requests
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor

import pyfiglet
from rich.rule import Rule
from rich.console import Console

from rich.table import Table
from rich.panel import Panel
from rich import box

# ==========================================
# ARGUMENT PARSER CONFIGURATION
# ==========================================
parse = argparse.ArgumentParser(description="crowbuster-DirectoryScanner")
parse.add_argument("-u", "--url", required=True, help="Uniform Resource Locator [URL]")
parse.add_argument("-w", "--wordlist", type=str, help="Path to wordlist")
parse.add_argument("-T", "--threads", default=15, type=int, help="Number of threads")
parse.add_argument("-o", "--output", type=str, help="Path to save discovered URLs (Optional)")
parse.add_argument("-d", "--depth", default=4, type=int, help="Maximum recursion depth (Default: 4)")
args = parse.parse_args()

# Clean target URL trailing slashes
url = args.url.strip("/")

# Load and sanitize wordlist payload
with open(args.wordlist, "r", errors="ignore") as f:
    words = [line.strip() for line in f if line.strip()]

# Initialize Rich UI Console & Banner
console = Console()
crowbuster = pyfiglet.figlet_format("CrowBuster", font="slant")

# Print Banner and target specifications
console.print(f"[cyan]{crowbuster}[/cyan]")
console.print(f"[cyan][*]Target:[/cyan][white] {url}")
console.print(f"[cyan][*]Wordlist: [/cyan][white]{os.path.basename(args.wordlist)} ({len(words)} words)")
console.print(f"[cyan][*]Threads: [/cyan][white]{args.threads}")
console.print(f"[cyan][*]Max Depth: [/cyan][white]{args.depth}")
if args.output:
    console.print(f"[cyan][*]Output File: [/cyan][white]{args.output}")
console.print(Rule(style="cyan"))

# ==========================================
# GLOBAL METRICS & MULTI-THREADING LOCKS
# ==========================================
found = 0
redirect = 0
unauthorized = 0
forbidden = 0
servererror = 0
total = 0

# Persistent HTTP session to enforce Connection Pooling (Keep-Alive)
session = requests.Session()

# Thread locks to prevent race conditions during global count & file updates
counter_lock = threading.Lock()
file_lock = threading.Lock()

# Live context status bar spinner
status = console.status("[bold cyan]Starting scan...", spinner="dots")

# ==========================================
# CORE SCANNING ENGINE (RECURSIVE)
# ==========================================
def scan(word, base_url=None, depth=0):
    global found, redirect, unauthorized, forbidden, servererror, total
    
    # Restrict recursive execution if current depth exceeds defined limit
    if depth > args.depth:
        return
        
    if base_url is None:
        base_url = url 
        
    # Thread-safe increment for real-time status update
    with counter_lock:
        total += 1    
        status.update(f"[bold cyan][*] Scanning... Total Requests: [bold white]{total}[/bold white][/bold cyan]")
        
    result = f"{base_url}/{word}"
    
    try:
        # Perform network request without automated redirection to capture exact HTTP states
        r = session.get(result, timeout=3, allow_redirects=False)
        
        if r.status_code in [200, 301, 302, 401, 500, 403]:

            # HTTP 200 OK - Resource Found
            if r.status_code == 200:
                console.print(f"[white][[/white][bold green]+[/bold green][white]][/white] [bold green]FOUND       [/bold green] [white]{result}[/white] [bold green]{r.status_code}[/bold green]")
                with counter_lock:
                    found += 1
                
                # Write discoveries sequentially using the dedicated file lock
                if args.output:
                    with file_lock:
                        with open(args.output, "a", encoding="utf-8") as out_file:
                            out_file.write(result + "\n")

            # HTTP 301/302 - Redirects
            elif r.status_code in [301, 302]:
                console.print(f"[white][[/white][bold cyan]*[/bold cyan][white]][/white] [bold cyan]REDIRECT    [/bold cyan] [white]{result}[/white] [bold cyan]{r.status_code}[/bold cyan]")   
                with counter_lock:
                    redirect += 1

            # HTTP 401 - Unauthorized
            elif r.status_code == 401:
                console.print(f"[white][[/white][bold yellow]![/bold yellow][white]][/white] [bold yellow]UNAUTHORIZED[/bold yellow] [white]{result}[/white] [bold yellow]{r.status_code}[/bold yellow]") 
                with counter_lock:
                    unauthorized += 1
            
            # HTTP 403 - Forbidden Access        
            elif r.status_code == 403:
                console.print(f"[white][[/white][bold red]![/bold red][white]][/white] [bold red]FORBIDDEN   [/bold red] [white]{result}[/white] [bold red]{r.status_code}[/bold red]")
                with counter_lock:
                    forbidden += 1
            
            # HTTP 500 - Internal Server Error        
            elif r.status_code == 500:
                console.print(f"[white][[/white][bold magenta]-[/bold magenta][white]][/white] [bold magenta]SERVER ERROR[/bold magenta] [white]{result}[/white] [bold magenta]{r.status_code}[/bold magenta]")       
                with counter_lock:
                    servererror += 1
                    
            # Recursive Crawling: Trigger child fuzzing on confirmed directory nodes
            for next_word in words:
                scan(next_word, base_url=result, depth=depth + 1)
                                      
    except requests.RequestException:
        pass

# ==========================================
# MAIN EXECUTION ROUTINE
# ==========================================
try:
    status.start()
    start_time = time.time()  

    # Leverage thread pooling to manage sub-worker threads
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        executor.map(scan, words)

    status.stop()
    end_time = time.time()    
    average_time = end_time - start_time

    # Construct and format metrics dashboard
    summary_table = Table(show_header=True, header_style="bold bright_white", box=box.ROUNDED, border_style="cyan")
    summary_table.add_column("Status Type", style="bold", width=18)
    summary_table.add_column("HTTP Code", justify="center", style="dim white")
    summary_table.add_column("Count", justify="right")

    summary_table.add_row("[white][[/white][bold green]+[/bold green][white]][/white] [green]Found[/green]", "200", f"[bold green]{found}[/bold green]")
    summary_table.add_row("[white][[/white][bold cyan]*[/bold cyan][white]][/white] [cyan]Redirect[/cyan]", "301/302", f"[bold cyan]{redirect}[/bold cyan]")
    summary_table.add_row("[white][[/white][bold yellow]![/bold yellow][white]][/white] [yellow]Unauthorized[/yellow]", "401", f"[bold yellow]{unauthorized}[/bold yellow]")
    summary_table.add_row("[white][[/white][bold red]![/bold red][white]][/white] [red]Forbidden[/red]", "403", f"[bold red]{forbidden}[/bold red]")
    summary_table.add_row("[white][[/white][bold magenta]-[/bold magenta][white]][/white] [magenta]Server Error[/magenta]", "500", f"[bold magenta]{servererror}[/bold magenta]")

    summary_table.add_section() 
    
    summary_table.add_row("[white]Total Requests[/white]", "-", f"[bold white]{total}[/bold white]")
    summary_table.add_row("[white]Max Depth Used[/white]", "-", f"[bold white]{args.depth}[/bold white]")
    summary_table.add_row("[bright_yellow]⏱ Time Taken[/bright_yellow]", "-", f"[bold bright_yellow]{average_time:.2f} seconds[/bold bright_yellow]")

    console.print("\n")
    console.print(Panel(summary_table, title="[bold gold3]  CROWBUSTER SCAN REPORT  [/bold gold3]", border_style="gold3", expand=False))
    
    # Conditional logging for saved artifacts notification
    if args.output and found > 0:
        console.print(f"[bold green][+] Results successfully saved to: [white]{args.output}[/white][/bold green]\n")
    elif args.output and found == 0:
        console.print(f"[bold yellow][!] No valid paths found to save in: [white]{args.output}[/white][/bold yellow]\n")

except KeyboardInterrupt:
    status.stop()
    console.print(f"\n[bold red][!] Scan stopped by user.[/bold red]")  
    os._exit(0)
