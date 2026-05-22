"""CLI: validate · project · run · audit · analyze."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from .analysis.figures import make_figures
from .analysis.load import build_frames
from .analysis.report import build_report
from .analysis.stats import all_tables
from .budget import project
from .cache import Cache
from .config import Config, Settings, load_config
from .matrix import expand
from .openrouter import OpenRouterClient
from .prompts import check_all_variants
from .runner import _effective_maps, key_for, load_validate_snapshot, run_tier

console = Console()


def _resolve(cfg: Config, args) -> tuple[str, str]:
    tier = getattr(args, "tier", None) or cfg.experiment.tier
    if tier not in cfg.tiers:
        console.print(f"[red]unknown tier {tier!r}; have {list(cfg.tiers)}[/red]")
        sys.exit(2)
    panel = getattr(args, "panel", None) or cfg.experiment.panel or cfg.tiers[tier]["default_panel"]
    return tier, panel


def _specs(cfg: Config, tier: str, panel: str):
    snap = load_validate_snapshot(cfg)
    reasoning_eff, max_temp, _ = _effective_maps(cfg, snap) if snap else ({}, {}, {})
    return expand(
        cfg, tier,
        panel_override=panel,
        reasoning_effective=reasoning_eff or None,
        max_temperature=max_temp or None,
    )


# ---------------------------------------------------------------- validate ---
async def _do_validate(cfg: Config, settings: Settings, no_probe: bool) -> dict:
    snap: dict = {"fetched_at": datetime.now(UTC).isoformat(), "models": {}}
    async with OpenRouterClient(settings.openrouter_api_key or "") as client:
        registry = await client.list_models()
        panel = cfg.models.panel("full")
        probe_targets = [m for m in panel if m.id in registry and m.reasoning and not no_probe]
        probes = await asyncio.gather(*(client.probe_reasoning(m.id) for m in probe_targets))
        probe_map = {m.id: pr for m, pr in zip(probe_targets, probes, strict=False)}
        for m in panel:
            info = registry.get(m.id)
            eff, rtok = probe_map.get(m.id, (bool(m.reasoning and no_probe), 0))
            snap["models"][m.id] = {
                "ok": info is not None,
                "reasoning_advertised": bool(info.supports_reasoning) if info else None,
                "reasoning_effective": bool(eff),
                "reasoning_tokens": rtok,
                "prompt_price": info.prompt_price if info else 0.0,
                "completion_price": info.completion_price if info else 0.0,
                "context_length": info.context_length if info else 0,
                "max_temperature": m.max_temperature,
            }
    return snap


def cmd_validate(cfg: Config, args) -> int:
    settings = Settings.from_env()
    if not settings.openrouter_api_key:
        console.print("[red]OPENROUTER_API_KEY not set[/red]")
        return 2

    violations = {k: v for k, v in check_all_variants(cfg.prompts).items() if v}
    if violations:
        console.print("[red]CONSTRUCT GUARD FAILED — wording drifted off the fixed construct:[/red]")
        for vid, probs in violations.items():
            console.print(f"  {vid}: {probs}")
        return 3
    console.print(f"[green]construct guard OK[/green] ({len(cfg.prompts.variants)} variants hold the fixed construct)")

    snap = asyncio.run(_do_validate(cfg, settings, args.no_probe))
    out = cfg.data_dir / "derived"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validate.json").write_text(json.dumps(snap, indent=2))

    t = Table(title="model registry / reasoning fidelity")
    for c in ("model", "live", "reason adv", "reason effective", "rtok", "$prompt/Mtok", "$compl/Mtok"):
        t.add_column(c)
    missing = []
    for mid, v in snap["models"].items():
        if not v["ok"]:
            missing.append(mid)
        t.add_row(
            mid,
            "✓" if v["ok"] else "[red]MISSING[/red]",
            str(v["reasoning_advertised"]),
            "[green]yes[/green]" if v["reasoning_effective"] else "no",
            str(v["reasoning_tokens"]),
            f"{v['prompt_price']*1e6:.3f}",
            f"{v['completion_price']*1e6:.3f}",
        )
    console.print(t)
    if missing:
        console.print(f"[red]{len(missing)} panel model id(s) not on OpenRouter: {missing}[/red]")
        console.print("[yellow]edit config/models.yaml before running[/yellow]")
        return 4
    console.print(f"[green]validate OK[/green] -> {out / 'validate.json'}")
    return 0


# ----------------------------------------------------------------- project ---
def _pricing(cfg: Config) -> dict:
    snap = load_validate_snapshot(cfg)
    if snap:
        _, _, pricing = _effective_maps(cfg, snap)
        return pricing
    return {}


def cmd_project(cfg: Config, args) -> int:
    tier, panel = _resolve(cfg, args)
    specs = _specs(cfg, tier, panel)
    pricing = _pricing(cfg)
    rep = project(cfg, tier, specs, pricing, panel=panel)

    t = Table(title=f"budget projection — tier {tier} · panel {panel}")
    for c in ("model", "calls", "in tok", "out tok", "reason tok", "est $"):
        t.add_column(c)
    for m in rep.per_model:
        t.add_row(m.model_id, str(m.calls), f"{m.input_tokens:,}", f"{m.output_tokens:,}",
                  f"{m.reasoning_tokens:,}", f"{m.cost_usd:.4f}")
    console.print(t)
    console.print(
        f"[bold]{rep.total_calls} calls[/bold] · raw ${rep.cost_raw_usd:.2f} · "
        f"with {rep.cost_banded_usd/max(rep.cost_raw_usd,1e-9):.1f}× safety band "
        f"[bold]${rep.cost_banded_usd:.2f}[/bold]"
    )
    if rep.missing_prices:
        console.print(f"[yellow]no price for {len(rep.missing_prices)} models (run `validate` first)[/yellow]")
    if rep.gated:
        console.print("[yellow]THOROUGH is hard-gated: `run --tier THOROUGH --confirm-budget`[/yellow]")
    out = cfg.data_dir / "derived" / "last_projection.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2))
    return 0


# --------------------------------------------------------------------- run ---
def cmd_run(cfg: Config, args) -> int:
    settings = Settings.from_env()
    if not settings.openrouter_api_key:
        console.print("[red]OPENROUTER_API_KEY not set[/red]")
        return 2
    tier, panel = _resolve(cfg, args)
    specs = _specs(cfg, tier, panel)

    only = getattr(args, "model", None)
    if only:
        specs = [s for s in specs if s.model_id == only]
        if not specs:
            console.print(
                f"[red]--model {only!r} matches no cells in tier {tier} · panel {panel}[/red] "
                f"(known ids: {[m.id for m in cfg.models.panel(panel)]})"
            )
            return 2
        console.print(f"[yellow]scoped to a single model:[/yellow] {only} ({len(specs)} planned cells)")

    rep = project(cfg, tier, specs, _pricing(cfg), panel=panel)
    console.print(
        f"tier [bold]{tier}[/bold] · panel {panel} · {rep.total_calls} calls · "
        f"projected ≈ ${rep.cost_banded_usd:.2f} (banded)"
    )
    if cfg.tiers[tier].get("gated") and not args.confirm_budget:
        console.print("[red]THOROUGH is hard-gated.[/red] Re-run with --confirm-budget after reviewing the projection above.")
        return 5

    last = {"pct": -1}

    def cb(done, total, spent):
        pct = int(100 * done / max(total, 1))
        if pct != last["pct"]:
            last["pct"] = pct
            console.print(f"  {done}/{total} ({pct}%)  spent ≈ ${spent:.3f}", end="\r")

    summary = asyncio.run(run_tier(cfg, tier, specs, confirm_budget=args.confirm_budget, progress_cb=cb))
    rd = cfg.data_dir / "runs" / summary.get("run_id", "")
    if rd.is_dir():
        (rd / "budget_projection.json").write_text(json.dumps(rep.to_dict(), indent=2))
    console.print("\n" + json.dumps(summary, indent=2))
    return 0 if summary.get("status") in ("complete", "aborted_max_usd") else 1


# ----------------------------------------------------------------- analyze ---
def cmd_analyze(cfg: Config, args) -> int:
    run_id = args.run or "latest"
    frames = build_frames(cfg, run_id)
    if frames["calls"].empty:
        console.print("[yellow]no cached records found for this run/tier[/yellow]")
        return 1
    tables = all_tables(frames)

    tdir = cfg.data_dir / "outputs" / "tables"
    fdir = cfg.data_dir / "outputs" / "figures"
    tdir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(tdir / f"{name}.csv", index=(name == "cross_model_agreement"))

    figures = make_figures(tables, frames, fdir)

    real_run = run_id
    latest = cfg.data_dir / "runs" / "latest.txt"
    if run_id == "latest" and latest.is_file():
        real_run = latest.read_text().strip()
    man_path = cfg.data_dir / "runs" / real_run / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.is_file() else {"tier": cfg.experiment.tier}

    report = build_report(cfg, real_run, manifest, tables, figures, cfg.data_dir / "outputs")
    console.print(f"[green]analyze done[/green] · {len(frames['calls'])} calls · "
                  f"{len(frames['picks'])} picks · tables -> {tdir} · report -> {report}")
    sp = tables["selection_probability"]
    if not sp.empty:
        top = sp.sort_values("p", ascending=False).head(10)[["model_id", "canonical", "p"]]
        console.print(top.to_string(index=False))
    return 0


# ------------------------------------------------------------------- audit ---
def cmd_audit(cfg: Config, args) -> int:
    """Collection-health check: planned vs cached, per model, so problems
    surface DURING collection, not at the end. Also a whole-corpus tally."""
    tier, panel = _resolve(cfg, args)
    specs = _specs(cfg, tier, panel)
    cache = Cache(cfg.data_dir)

    from collections import Counter, defaultdict
    by = defaultdict(Counter)
    for s in specs:
        k, *_ = key_for(cfg, s)
        rec = cache.load(s.model_id, k)
        if rec is None:
            by[s.model_id]["missing"] += 1
        elif rec.parsed is not None and not rec.parsed.refused:
            by[s.model_id]["good"] += 1
        elif (rec.parsed and rec.parsed.refused) or rec.parse_status.value == "refused":
            by[s.model_id]["refused"] += 1
        elif rec.error:
            by[s.model_id]["transient"] += 1   # retried on next run
        else:
            by[s.model_id]["failed"] += 1       # parse-failed-with-content

    t = Table(title=f"collection audit — tier {tier} · panel {panel}")
    for c in ("model", "planned", "good", "refused", "failed", "transient", "missing", "%usable"):
        t.add_column(c)
    problems: list[str] = []
    for mid in sorted(by):
        c = by[mid]
        planned = sum(c.values())
        usable = c["good"] + c["refused"]  # refusal is a valid recorded outcome
        pct = 100 * usable / planned if planned else 0
        t.add_row(mid, str(planned), str(c["good"]), str(c["refused"]), str(c["failed"]),
                  str(c["transient"]), str(c["missing"]), f"{pct:.0f}%")
        if planned and (c["missing"] + c["transient"]) / planned > 0.25:
            problems.append(f"{mid}: {c['missing']+c['transient']}/{planned} not yet collected")
        if planned and c["good"] == 0 and c["refused"] == 0:
            problems.append(f"{mid}: ZERO usable responses")
    console.print(t)

    # whole paid corpus (all runs, all models incl. retained inactive ones)
    allc = Counter()
    cost = 0.0
    seen = set()
    for r in cache.iter_records():
        allc[r.parse_status.value] += 1
        cost += r.cost_actual_usd or 0.0
        seen.add(r.spec.model_id)
    console.print(f"[bold]whole corpus[/bold]: {sum(allc.values())} records across "
                  f"{len(seen)} models · {dict(allc)} · paid ≈ ${cost:.2f}")
    arch = cfg.data_dir / "raw" / "_archive"
    if arch.is_dir():
        n = sum(1 for _ in arch.rglob("*.json"))
        console.print(f"[dim]archived superseded paid responses: {n} (never deleted)[/dim]")
    if problems:
        console.print("[yellow]ATTENTION:[/yellow]")
        for pmsg in problems:
            console.print(f"  - {pmsg}")
    else:
        console.print("[green]collection healthy[/green]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmchar")
    p.add_argument("--config-dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="re-resolve model ids + reasoning-fidelity probe")
    v.add_argument("--no-probe", action="store_true", help="skip the reasoning probe (no paid calls)")
    v.set_defaults(func=cmd_validate)

    pr = sub.add_parser("project", help="cost/token projection")
    pr.add_argument("--tier")
    pr.add_argument("--panel")
    pr.set_defaults(func=cmd_project)

    r = sub.add_parser("run", help="execute a tier (resumable)")
    r.add_argument("--tier")
    r.add_argument("--panel")
    r.add_argument("--model", help="scope the run to a single model id (e.g. anthropic/claude-sonnet-4.6)")
    r.add_argument("--confirm-budget", action="store_true")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("analyze", help="tables + figures + report")
    a.add_argument("--run", default="latest",
                   help="run id, 'latest', or 'all' (entire paid corpus — final reporting)")
    a.set_defaults(func=cmd_analyze)

    au = sub.add_parser("audit", help="collection-health check (planned vs cached, per model)")
    au.add_argument("--tier")
    au.add_argument("--panel")
    au.set_defaults(func=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config_dir)
    return args.func(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
