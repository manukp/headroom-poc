"""Result capture + Rich terminal visualization (D2).

Two surfaces: (1) a durable JSON artifact per run under results/<timestamp>/, and
(2) Rich tables in the terminal. A web UI / exporter remains deferred (D2).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import REPO_ROOT, Config


def _make_console() -> Console:
    """A Console that tolerates Windows legacy code pages by forcing UTF-8."""
    import io
    import sys

    stream = sys.stdout
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        else:  # pragma: no cover
            stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace", line_buffering=True)
    except Exception:  # pragma: no cover - fall back to default stdout
        stream = sys.stdout
    return Console(file=stream)


def _pct(v: Any) -> str:
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "-"


def write_run(cfg: Config, results: list[dict[str, Any]],
              accuracy: list[dict[str, Any]], judgements: list[dict[str, Any]],
              meta: dict[str, Any]) -> Path:
    out_dir = REPO_ROOT / cfg.run.results_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "config": cfg.raw,
        "compression_results": results,
        "accuracy_results": accuracy,
        "judgements": judgements,
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return run_dir


def render(cfg: Config, results: list[dict[str, Any]],
           accuracy: list[dict[str, Any]], judgements: list[dict[str, Any]],
           meta: dict[str, Any], run_dir: Path) -> None:
    # Force UTF-8 so legacy Windows consoles (cp1252) don't choke on box glyphs.
    console = _make_console()
    console.print(Panel.fit(
        f"[bold]Headroom PoC[/bold]  -  mode=[cyan]{cfg.run.mode}[/cyan]  "
        f"-  headroom-ai=[cyan]{meta.get('headroom_version')}[/cyan]  "
        f"-  tokenizer=[cyan]{meta.get('tokenizer')}[/cyan]\n"
        f"config: {cfg.path}\nresults: {run_dir}",
        title="Run summary"))

    _render_compression(console, results)
    _render_fidelity(console, results)
    if accuracy:
        _render_accuracy(console, accuracy, judgements)

    if meta.get("notes"):
        console.print(Panel("\n".join(f"- {n}" for n in meta["notes"]),
                            title="Notes / caveats", border_style="yellow"))


def _render_compression(console: Console, results: list[dict[str, Any]]) -> None:
    t = Table(title="Token reduction (compression leg)", header_style="bold")
    for col in ("Feature", "Input", "Before", "After", "Saved", "Savings%", "Status"):
        t.add_column(col, overflow="fold")
    for r in results:
        if not r.get("ok"):
            t.add_row(r.get("feature", "?"), r.get("input_id", "-"),
                      "-", "-", "-", "-",
                      f"[red]skip/err[/red] {r.get('skipped') or r.get('error','')}"[:60])
            continue
        t.add_row(
            r.get("feature", "?"), r.get("input_id", "-"),
            str(r.get("tokens_before", "-")), str(r.get("tokens_after", "-")),
            str(r.get("tokens_saved", "-")), _pct(r.get("savings_percent")),
            "[green]ok[/green]")
    console.print(t)


def _render_fidelity(console: Console, results: list[dict[str, Any]]) -> None:
    t = Table(title="Fidelity (forward-pass + verbatim + reversibility)",
              header_style="bold")
    for col in ("Feature", "Input", "Diff class", "Verbatim survival",
                "Lost", "Reversible (SmartCrusher)"):
        t.add_column(col, overflow="fold")
    any_row = False
    for r in results:
        if not r.get("ok"):
            continue
        diff = r.get("diff") or {}
        vb = r.get("verbatim") or {}
        rev = r.get("reversibility") or {}
        rev_str = "-"
        if rev:
            if rev.get("claims_lossless"):
                match = rev.get("structural_match")
                recon = "match" if match else ("MISMATCH" if match is False else "?")
                rev_str = f"strategy={rev.get('strategy','')[:24]} recon={recon}"
            else:
                rev_str = f"[yellow]lossy[/yellow] {rev.get('strategy','')[:24]}"
        vb_str = "-"
        if vb.get("checked"):
            vb_str = f"{vb.get('survived')}/{vb.get('checked')} ({_pct(vb['survival_rate']*100)})"
        lost = ", ".join(vb.get("lost", []))[:40] or "-"
        diff_class = diff.get("classification", "-")
        if diff_class == "paraphrase/rewrite":
            diff_class = f"[red]{diff_class}[/red]"
        t.add_row(r.get("feature", "?"), r.get("input_id", "-"),
                  diff_class, vb_str, lost, rev_str)
        any_row = True
    if any_row:
        console.print(t)


def _render_accuracy(console: Console, accuracy: list[dict[str, Any]],
                     judgements: list[dict[str, Any]]) -> None:
    jmap = {j["input_id"]: j for j in judgements}
    t = Table(title="Accuracy (original vs compressed context, LLM-as-judge)",
              header_style="bold")
    for col in ("Input", "HR saved%", "Orig in/out tok", "Comp in/out tok",
                "Equivalent", "Fact overlap", "Differences"):
        t.add_column(col, overflow="fold")
    for a in accuracy:
        if not a.get("ok"):
            t.add_row(a.get("input_id", "-"), "-", "-", "-",
                      f"[red]err[/red] {a.get('error','')}"[:40], "-", "-")
            continue
        hr = a.get("headroom", {})
        o, c = a["original"], a["compressed"]
        j = jmap.get(a["input_id"], {})
        verdict = j.get("verdict", {})
        eq = verdict.get("equivalent")
        eq_str = ("[green]yes[/green]" if eq is True else
                  "[red]no[/red]" if eq is False else "?")
        ov = j.get("deterministic_overlap", {})
        ov_str = _pct(ov["overlap"] * 100) if ov.get("available") else "-"
        diffs = ", ".join(verdict.get("differences", []))[:40] or "-"
        t.add_row(
            a["input_id"],
            _pct(hr.get("headroom_compression_ratio", 0) * 100),
            f"{o.get('bedrock_input_tokens')}/{o.get('bedrock_output_tokens')}",
            f"{c.get('bedrock_input_tokens')}/{c.get('bedrock_output_tokens')}",
            eq_str, ov_str, diffs)
    console.print(t)
