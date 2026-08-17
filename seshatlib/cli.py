import argparse
import os
import sys
from pathlib import Path

from . import __version__
from . import installer
from . import manifest as manifest_mod
from . import planner, providers
from . import state as state_mod
from .installer import InstallerError
from .manifest import ManifestError
from .output import Reporter
from .planner import PlanError
from .providers import ProviderError
from .state import Lock, LockError, StateError
from .templates import TemplateError


class CliError(Exception):
    pass


def _repo_root():
    env = os.environ.get("SESHAT_REPO")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _home():
    env = os.environ.get("SESHAT_HOME")
    if env:
        return Path(env)
    return Path.home()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="seshat",
        description="Stateful, ownership-aware installer for this dotfiles repository.",
    )
    parser.add_argument("--version", action="version", version=f"seshat {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_install = sub.add_parser("install", help="install a bundle (default when omitted)")
    p_install.add_argument("bundle", nargs="?", default="default")
    p_install.add_argument("--yes", action="store_true", help="apply without confirmation")
    p_install.add_argument(
        "--set", action="append", default=[], dest="set_vars", metavar="NAME=VALUE",
        help="set a bundle variable",
    )
    p_install.add_argument("--json", action="store_true", help="machine-readable output")
    p_install.add_argument("--no-color", action="store_true")
    p_install.add_argument("--automatic", action="store_true", help=argparse.SUPPRESS)

    p_list = sub.add_parser("list", help="show bundles and their state")
    p_list.add_argument("bundle", nargs="?")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")
    p_list.add_argument("--no-color", action="store_true")

    p_remove = sub.add_parser("remove", help="remove an optional bundle")
    p_remove.add_argument("bundle")
    p_remove.add_argument("--yes", action="store_true", help="apply without confirmation")
    p_remove.add_argument("--json", action="store_true", help="machine-readable output")
    p_remove.add_argument("--no-color", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    repo = _repo_root()
    home = _home()
    rep = Reporter(json_mode=getattr(args, "json", False), color=not getattr(args, "no_color", False))
    try:
        if args.command == "install":
            return cmd_install(args, repo, home, rep)
        if args.command == "list":
            return cmd_list(args, repo, home, rep)
        if args.command == "remove":
            return cmd_remove(args, repo, home, rep)
        return 1
    except (
        ManifestError,
        StateError,
        InstallerError,
        ProviderError,
        TemplateError,
        PlanError,
        LockError,
        CliError,
    ) as e:
        rep.error(str(e))
        rep.finish({"ok": False, "error": str(e)})
        return 1


def _parse_set_vars(set_vars):
    out = {}
    for entry in set_vars:
        if "=" not in entry:
            raise CliError(f"--set expects NAME=VALUE, got: {entry}")
        name, value = entry.split("=", 1)
        out[name] = value
    return out


def resolve_variables(bundle, state, sets, environ, automatic):
    remembered = (state.bundles.get(bundle.name) or {}).get("variables") or {}
    out = {}
    for name, var in bundle.variables.items():
        if name in sets:
            out[name] = sets[name]
        elif name in remembered:
            out[name] = remembered[name]
        elif var.environment and var.environment in environ:
            out[name] = environ[var.environment]
        elif var.default is not None:
            out[name] = var.default
        elif not automatic and sys.stdin.isatty():
            value = input(f"{bundle.name}: value for {name}: ").strip()
            if not value:
                raise CliError(f"variable {name} for bundle {bundle.name} has no value")
            out[name] = value
        else:
            raise CliError(
                f"variable {name} for bundle {bundle.name} has no value; pass --set {name}=VALUE"
            )
    return out


def _install_order(bundles, state, target):
    order = []
    for dep in manifest_mod.resolve_order(bundles, target):
        if dep == target or dep not in state.bundles:
            order.append(dep)
    return order


def _confirm(plan, args, rep):
    if args.yes or getattr(args, "automatic", False):
        return True
    if not sys.stdin.isatty():
        return True
    answer = input(f"Apply {len(plan.changes)} change(s)? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _report_plan(plan, rep):
    for c in plan.changes:
        rep.change(c.kind, c.dest, c.bundle, c.detail)
    for s in plan.skipped:
        rep.skip(s.dest, s.reason)
    for b in plan.blocked:
        rep.blocked(b.dest, b.reason, b.key)


def cmd_install(args, repo, home, rep):
    seshat_dir = state_mod.ensure_seshat_dir(repo / ".seshat")
    facts = manifest_mod.gather_facts()
    sets = _parse_set_vars(args.set_vars)
    with Lock(seshat_dir):
        for txn_id in installer.recover(seshat_dir):
            rep.warn(f"recovered incomplete transaction {txn_id}")
        bundles = manifest_mod.load_bundles(repo)
        if args.bundle not in bundles:
            raise CliError(f"unknown bundle: {args.bundle}")
        manifest_mod.check_overlaps(bundles, facts)
        if not manifest_mod.bundle_active(bundles[args.bundle], facts):
            raise CliError(f"bundle {args.bundle} is not available on this platform")
        state = state_mod.load_state(seshat_dir)
        order = _install_order(bundles, state, args.bundle)

        declared = set()
        for name in order:
            declared.update(bundles[name].variables)
        unknown_sets = set(sets) - declared
        if unknown_sets:
            raise CliError(f"--set names not declared by {args.bundle}: {sorted(unknown_sets)}")

        variables_by_bundle = {}
        for name in order:
            variables_by_bundle[name] = resolve_variables(
                bundles[name], state, sets, os.environ, args.automatic
            )

        for name in order:
            missing = providers.missing_commands(bundles[name].requires_commands)
            if missing:
                raise CliError(f"bundle {name} requires missing commands: {', '.join(missing)}")
        for name in order:
            if bundles[name].requires_kauket:
                rep.info(f"running kauket prerequisites for {name}")
                providers.run_kauket(bundles[name].requires_kauket)

        source_commit = providers.repo_head_commit(repo)
        staged, staged_order = installer.stage(
            repo,
            [bundles[n] for n in order],
            facts,
            variables_by_bundle,
            seshat_dir / "staging" / "current",
            home,
            source_commit,
        )
        plan = planner.plan_install(
            repo, bundles, order, staged, staged_order, state, facts, home,
            args.automatic, source_commit, variables_by_bundle,
        )
        _report_plan(plan, rep)
        needs_apply = bool(plan.actions) or plan.new_state.data != state.data
        applied = False
        if needs_apply:
            if plan.changes and not _confirm(plan, args, rep):
                rep.info("aborted")
                rep.finish({"ok": False, "aborted": True})
                return 1
            installer.Transaction(seshat_dir, home).apply(plan.actions, plan.new_state)
            applied = True
            rep.info(f"installed {args.bundle}" if plan.changes else f"{args.bundle}: state refreshed")
        else:
            rep.info("nothing to do")
        if plan.blocked:
            rep.error(
                f"{len(plan.blocked)} target(s) blocked; run 'seshat list {args.bundle}' for details"
            )
        result = {
            "ok": not plan.blocked,
            "bundle": args.bundle,
            "applied": applied,
            "changes": len(plan.changes),
            "skipped": len(plan.skipped),
            "blocked": [
                {"dest": b.dest, "key": b.key, "reason": b.reason, "target": b.target_id}
                for b in plan.blocked
            ],
        }
        rep.finish(result)
        return 2 if plan.blocked else 0


def cmd_list(args, repo, home, rep):
    facts = manifest_mod.gather_facts()
    bundles = manifest_mod.load_bundles(repo)
    seshat_dir = repo / ".seshat"
    state = state_mod.load_state(seshat_dir) if (seshat_dir / "state.yml").exists() else state_mod.State()
    pending = planner.has_pending_txn(seshat_dir)
    if pending:
        rep.warn("an incomplete transaction exists; run 'seshat install' to recover")

    names = sorted(set(bundles) | set(state.bundles), key=lambda n: (n != "default", n))
    if args.bundle:
        if args.bundle not in bundles and args.bundle not in state.bundles:
            raise CliError(f"unknown bundle: {args.bundle}")
        names = [args.bundle]

    reports = [
        planner.bundle_report(repo, bundles, state, name, facts, home, pending) for name in names
    ]
    if args.bundle:
        r = reports[0]
        rep.info(f"Bundle:       {r['name']}")
        rep.info(f"State:        {r['state']}")
        rep.info(f"Installed:    {_short(r['installed_commit'])}")
        if r["description"]:
            rep.info(f"Description:  {r['description']}")
        if r["problems"]:
            for p in r["problems"]:
                rep.warn(p)
        if r["targets"]:
            rep.info("")
            rep.info("Targets:")
            for t in r["targets"]:
                if t.get("keys") is not None:
                    rep.info(f"  {t['dest']}")
                    for k in t["keys"]:
                        rep.info(f"    {k['state']:<10} {k['key']:<15} {k['owner']}")
                else:
                    rep.info(f"  {t['state']:<10} {t['dest']}")
    else:
        rows = [
            [r["name"], r["state"], _short(r["installed_commit"]) or "-"]
            for r in reports
        ]
        rep.table(["BUNDLE", "STATE", "INSTALLED FROM"], rows)
    rep.finish({"ok": True, "bundles": reports})
    return 0


def _short(commit):
    if not commit or commit == "unknown":
        return commit or ""
    return commit[:7]


def cmd_remove(args, repo, home, rep):
    seshat_dir = state_mod.ensure_seshat_dir(repo / ".seshat")
    facts = manifest_mod.gather_facts()
    with Lock(seshat_dir):
        for txn_id in installer.recover(seshat_dir):
            rep.warn(f"recovered incomplete transaction {txn_id}")
        bundles = manifest_mod.load_bundles(repo)
        state = state_mod.load_state(seshat_dir)
        staged_default = {}
        needs_default = any(
            rec.get("replaced_default")
            for rec in state.targets_owned_by(args.bundle).values()
            if isinstance(rec, dict)
        )
        if needs_default and "default" in bundles:
            source_commit = providers.repo_head_commit(repo)
            staged_default, _ = installer.stage(
                repo,
                [bundles["default"]],
                facts,
                {"default": (state.bundles.get("default") or {}).get("variables") or {}},
                seshat_dir / "staging" / "remove",
                home,
                source_commit,
            )
        plan = planner.plan_remove(repo, bundles, args.bundle, state, staged_default, facts, home)
        _report_plan(plan, rep)
        if plan.blocked:
            rep.error("removal refused; resolve the blocked targets first")
            rep.finish({"ok": False, "blocked": len(plan.blocked)})
            return 2
        if not plan.actions and plan.new_state.data == state.data:
            rep.info("nothing to do")
            rep.finish({"ok": True, "applied": False})
            return 0
        if plan.changes and not _confirm(plan, args, rep):
            rep.info("aborted")
            rep.finish({"ok": False, "aborted": True})
            return 1
        installer.Transaction(seshat_dir, home).apply(plan.actions, plan.new_state)
        rep.info(f"removed {args.bundle}")
        rep.finish({"ok": True, "applied": True, "changes": len(plan.changes)})
        return 0


if __name__ == "__main__":
    sys.exit(main())
