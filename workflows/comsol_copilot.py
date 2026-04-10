#!/usr/bin/env python
"""
comsol_copilot.py — Autonomous 2D→3D COMSOL Co-Pilot
======================================================
Single command that runs the full pipeline:

  1. MEMORIZE  — run memorize_workflows2.py to capture 2D model recipe
  2. CONVERT   — run convert_2D_to_3D.py to build 3D model
  3. PAUSE     — wait for 3 manual GUI clicks (Thermodynamics setup)
  4. VALIDATE  — run comsol_validator.validate_model()
  5. AUTO-FIX  — run comsol_autofixer.autofix() (max 3 retries)
  6. RUN STUDY — trigger a study solve on the COMSOL server
  7. REPORT    — print final status and save to comsol_knowledge_base.json

Usage:
  python comsol_copilot.py [--model-key KEY] [--output FILE] [--skip-memorize]
                            [--skip-convert] [--skip-gui-pause] [--study STD_TAG]
                            [--mesh-size N] [--dry-run]

Examples:
  # Full pipeline (first time):
  python comsol_copilot.py

  # Re-run only from convert onward (recipe already exists):
  python comsol_copilot.py --skip-memorize

  # Skip memorize + convert, just validate + fix + run:
  python comsol_copilot.py --skip-memorize --skip-convert

  # Run a specific study:
  python comsol_copilot.py --skip-memorize --skip-convert --study std4
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback

import mph

COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment
RECIPE_FILE  = "comsol_recipes.json"
OUTPUT_FILE  = os.getenv("COMSOL_OUTPUT_FILE", "output_3D.mph")  # configured via config.py / environment
KB_FILE      = "comsol_knowledge_base.json"
MODEL_KEY    = os.getenv("COMSOL_MODEL_KEY", "")  # configured via config.py / environment — set to your model's recipe key
PYTHON_BIN   = sys.executable   # re-use whichever Python launched this script


# ── HELPERS ───────────────────────────────────────────────────────────────

def banner(msg, char="═"):
    line = char * 68
    print(f"\n{line}\n  {msg}\n{line}")

def step(msg):  print(f"\n  ▶ {msg}")
def ok(msg):    print(f"  ✓ {msg}")
def warn(msg):  print(f"  ⚠ {msg}")
def err(msg):   print(f"  ✗ {msg}")


def run_script(script_path, label, timeout=600):
    """
    Run a Python script as a subprocess using the same interpreter.
    Streams stdout/stderr live. Returns (success, output_text).
    """
    step(f"Running {label}…")
    output_lines = []
    try:
        proc = subprocess.Popen(
            [PYTHON_BIN, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(script_path)),
        )
        for line in proc.stdout:
            print(f"    {line}", end="")
            output_lines.append(line)
        proc.wait(timeout=timeout)
        success = proc.returncode == 0
        if success:
            ok(f"{label} completed (exit 0)")
        else:
            warn(f"{label} exited with code {proc.returncode}")
        return success, "".join(output_lines)
    except subprocess.TimeoutExpired:
        proc.kill()
        err(f"{label} timed out after {timeout}s")
        return False, "TIMEOUT"
    except Exception as e:
        err(f"{label} failed: {e}")
        return False, str(e)


COMSOL_BIN = os.getenv("COMSOL_BIN", "/Applications/COMSOL63/Multiphysics/bin/comsol")  # configured via config.py / environment

GAS_COMPOSITIONS = [
    ("61He 36.5H2 2.5CH4",  "He=0.61,  H2=0.365, CH4=0.025, N2=0.0"),
    ("97.5H2 2.5CH4",       "He=0,     H2=0.975, CH4=0.025, N2=0.0"),
    ("10N2 51He 36.5H2...", "He=0.51,  H2=0.365, CH4=0.025, N2=0.10"),
    ("31N2 30He H2 2.5CH4", "He=0.3,   H2=0.365, CH4=0.025, N2=0.31"),
    ("61N2 36.5H2 2.5CH4",  "He=0,     H2=0.365, CH4=0.025, N2=0.61"),
]


def _snapshot_gui_state(jm):
    """
    Capture a lightweight snapshot of GUI-changeable state:
    material tags, thermodynamics feature tags, switch members.
    Returns a dict.
    """
    snap = {"mat_tags": [], "thermo_feat_tags": [], "switch_members": {}}
    try:
        comp = jm.component("comp1")
        snap["mat_tags"] = [str(t) for t in list(comp.material().tags())]
        for t in snap["mat_tags"]:
            try:
                node = comp.material(t)
                if str(node.getType()) == "Switch":
                    members = []
                    try:
                        for mt in list(node.member().tags()):
                            members.append(str(mt))
                    except Exception:
                        pass
                    snap["switch_members"][t] = members
            except Exception:
                pass
    except Exception:
        pass
    try:
        thermo = jm.thermodynamics()
        snap["thermo_feat_tags"] = [str(t) for t in list(thermo.feature().tags())]
    except Exception:
        pass
    return snap


def _watch_gui_changes(jm, stop_event, poll_interval=3):
    """
    Background thread: poll COMSOL model for GUI-triggered changes.
    Prints live notifications and returns a change log via a list.
    """
    log = []
    baseline = _snapshot_gui_state(jm)
    reported = set()

    def note(msg):
        entry = {"time": time.strftime("%H:%M:%S"), "event": msg}
        log.append(entry)
        print(f"\n  [watcher {entry['time']}] {msg}")

    while not stop_event.is_set():
        time.sleep(poll_interval)
        try:
            curr = _snapshot_gui_state(jm)

            # New materials (Generate Material)
            new_mats = set(curr["mat_tags"]) - set(baseline["mat_tags"])
            for t in sorted(new_mats):
                key = f"new_mat:{t}"
                if key not in reported:
                    reported.add(key)
                    note(f"New material detected: '{t}' — Generate Material ran")

            # New thermodynamics features (Define System)
            new_thermo = set(curr["thermo_feat_tags"]) - set(baseline["thermo_feat_tags"])
            for t in sorted(new_thermo):
                key = f"new_thermo:{t}"
                if key not in reported:
                    reported.add(key)
                    note(f"New thermodynamics feature: '{t}' — Define System ran")

            # Switch members added
            for sw_tag, members in curr["switch_members"].items():
                prev_members = baseline.get("switch_members", {}).get(sw_tag, [])
                for m in members:
                    key = f"switch:{sw_tag}:{m}"
                    if key not in reported:
                        reported.add(key)
                        note(f"Material Switch '{sw_tag}' gained member '{m}'")

            # Update baseline with any new discoveries
            baseline = curr

        except Exception:
            pass  # server briefly unavailable between operations

    return log


def gui_watch_and_pause(model_path, jm, port=COMSOL_PORT):
    """
    Like gui_pause() but also runs a background watcher to learn from GUI clicks.
    Returns change_log (list of dicts).
    """
    stop_event = threading.Event()
    change_log = []

    def _watcher():
        result = _watch_gui_changes(jm, stop_event)
        change_log.extend(result)

    watcher_thread = threading.Thread(target=_watcher, daemon=True)
    watcher_thread.start()

    gui_pause(model_path, port)  # blocks on input()

    stop_event.set()
    watcher_thread.join(timeout=5)

    if change_log:
        ok(f"Watcher captured {len(change_log)} GUI event(s):")
        for entry in change_log:
            print(f"    [{entry['time']}] {entry['event']}")
    else:
        warn("Watcher detected no model changes — did you complete all 3 steps?")

    return change_log


def try_open_comsol_gui(model_path):
    """
    Try to open COMSOL GUI with the saved model file.
    Falls back to macOS 'open' if the COMSOL binary launch fails.
    Returns True if a launch was attempted.
    """
    if os.path.exists(COMSOL_BIN):
        try:
            subprocess.Popen(
                [COMSOL_BIN, "-open", model_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ok("COMSOL GUI launch attempted (comsol -open)")
            return True
        except Exception as e:
            warn(f"comsol -open failed: {e} — trying 'open'")

    # macOS fallback: open with default app
    try:
        subprocess.Popen(["open", model_path])
        ok("Model opened with macOS 'open' command")
        return True
    except Exception as e:
        warn(f"'open' also failed: {e}")
        return False


def verify_gui_steps(jm):
    """
    Check whether the 3 GUI thermodynamics steps were completed.
    Returns list of issue strings (empty = all good).
    """
    issues = []
    try:
        comp = jm.component("comp1")
        mat_tags = [str(t) for t in list(comp.material().tags())]

        # Generated gas materials from Thermodynamics have tags like "pp1mat1", "pp1mat2", etc.
        gas_mats = [t for t in mat_tags if "pp" in t and t != "pp1"]
        if gas_mats:
            ok(f"Found {len(gas_mats)} generated gas material(s): {gas_mats}")
        else:
            issues.append("No generated gas materials found — did you click Generate Material?")

        # Check for Material Switch (sw1)
        switches = []
        for t in mat_tags:
            try:
                if str(comp.material(t).getType()) == "Switch":
                    switches.append(t)
            except Exception:
                pass
        if switches:
            ok(f"Material Switch found: {switches}")
        else:
            issues.append("No Material Switch found — thermodynamics may not be fully initialized")

    except Exception as e:
        issues.append(f"Could not inspect materials: {e}")

    return issues


def gui_pause(model_path, port=COMSOL_PORT):
    """
    Save model, try to open COMSOL GUI, then block until user confirms
    the 3 manual thermodynamics steps are done.
    """
    basename = os.path.basename(model_path)
    w = 66  # box inner width

    def row(text=""):
        padded = f"  {text}"
        return f"║{padded:<{w}}║"

    gas_lines = [
        f"  {'Gas mix':<28} {'Mole fractions'}"
    ] + [
        f"  • {name:<26} {fracs}" for name, fracs in GAS_COMPOSITIONS
    ]

    print("\n╔" + "═" * w + "╗")
    print(row("MANUAL GUI STEPS REQUIRED"))
    print("╠" + "═" * w + "╣")
    print(row())
    print(row(f"Model: {basename}"))
    print(row(f"Server: localhost:{port}"))
    print(row())
    print(row("IMPORTANT: Work on the LIVE SERVER model, not a local file."))
    print(row("The watcher only sees changes made via the server connection."))
    print(row())
    print(row("Connect COMSOL GUI to the server:"))
    print(row(f"  File → Connect to Server → localhost → port {port}"))
    print(row(f"  The model '{basename}' will appear in the tree."))
    print(row())
    print(row("  (If GUI is not open at all, it will launch now — but"))
    print(row("   then connect to server as above before doing the steps.)"))
    print(row())
    print(row("Do these 3 steps IN the server-connected model:"))
    print(row("  1. Right-click Thermodynamic System 1 (pp1)"))
    print(row("     → Define System"))
    print(row("  2. Right-click pp1 → Generate Material"))
    print(row("  3. Set mole fractions for each gas:"))
    for line in gas_lines:
        print(row(line))
    print(row())
    print("╚" + "═" * w + "╝")

    # Attempt to open GUI if not already open (user still needs to connect to server)
    step("Attempting to open COMSOL GUI if not already open…")
    try_open_comsol_gui(model_path)

    input("\n  Press Enter when done with GUI steps… ")
    ok("GUI steps confirmed — verifying…")


def get_model(client, model_name_hint=None):
    """
    Return the most relevant model from the server.
    If model_name_hint is given, prefer models whose name contains it.
    """
    models = client.models()
    if not models:
        raise RuntimeError("No models loaded on COMSOL server (port 2036)")
    if model_name_hint:
        for m in reversed(models):
            if model_name_hint.lower() in str(m.name()).lower():
                return m
    return models[-1]


def run_study(jm, study_tag, timeout=3600):
    """
    Run a COMSOL study via jm.study(tag).run() — the correct API that
    generates solver sequences from the study settings and blocks until done.
    Returns (success, message).
    """
    step(f"Running study '{study_tag}'…")
    try:
        study_tags = [str(t) for t in list(jm.study().tags())]
        if study_tag not in study_tags:
            return False, f"Study '{study_tag}' not found. Available: {study_tags}"

        step(f"  Calling jm.study('{study_tag}').run() — this will block until solved…")
        t0 = time.time()

        # This is the correct call: it builds the full solver sequence from
        # the study node and runs it synchronously.
        jm.study(study_tag).run()

        elapsed = time.time() - t0
        ok(f"Study '{study_tag}' completed in {elapsed:.1f}s")
        return True, f"Study '{study_tag}' solved OK ({elapsed:.1f}s)"

    except Exception as e:
        err_str = str(e)
        err(f"Study '{study_tag}' failed: {err_str[:300]}")
        return False, err_str


def save_knowledge(model_name, pipeline_result, kb_file=KB_FILE):
    """Append pipeline run result to the knowledge base JSON."""
    kb = {}
    if os.path.exists(kb_file):
        try:
            with open(kb_file) as f:
                kb = json.load(f)
        except Exception:
            pass

    if "runs" not in kb:
        kb["runs"] = []

    kb["runs"].append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model_name,
        **pipeline_result,
    })

    with open(kb_file, "w") as f:
        json.dump(kb, f, indent=2)
    ok(f"Knowledge base updated: {kb_file}")


# ── PIPELINE ──────────────────────────────────────────────────────────────

def run_pipeline(args):
    banner("COMSOL AI Co-Pilot — Autonomous 2D→3D Pipeline")

    pipeline_result = {
        "status": "unknown",
        "steps": {},
        "errors": [],
        "warnings": [],
    }
    here = os.path.dirname(os.path.abspath(__file__))

    # ── STEP 1: MEMORIZE ──────────────────────────────────────────────────
    if not args.skip_memorize:
        banner("Step 1 / 6 — Memorize 2D model", char="─")
        memorizer = os.path.join(here, "memorize_workflows2.py")
        ok_mem, out_mem = run_script(memorizer, "memorize_workflows2.py")
        pipeline_result["steps"]["memorize"] = "ok" if ok_mem else "failed"
        if not ok_mem:
            err("Memorize failed — check COMSOL server has 2D model loaded")
            pipeline_result["status"] = "failed"
            pipeline_result["errors"].append("memorize step failed")
            if not args.dry_run:
                return pipeline_result
    else:
        ok("Memorize skipped (--skip-memorize)")
        pipeline_result["steps"]["memorize"] = "skipped"

    # ── STEP 2: CONVERT ───────────────────────────────────────────────────
    if not args.skip_convert:
        banner("Step 2 / 6 — Convert 2D → 3D", char="─")
        converter = os.path.join(here, "convert_2D_to_3D.py")
        ok_conv, out_conv = run_script(converter, "convert_2D_to_3D.py")
        pipeline_result["steps"]["convert"] = "ok" if ok_conv else "warned"
        if not ok_conv:
            warn("Converter had non-zero exit — may still have produced a model, continuing…")
    else:
        ok("Convert skipped (--skip-convert)")
        pipeline_result["steps"]["convert"] = "skipped"

    # ── Connect to server for remaining steps ─────────────────────────────
    banner("Connecting to COMSOL server", char="─")
    try:
        client = mph.Client(port=COMSOL_PORT)
        model = get_model(client, model_name_hint="3D")
        jm = model.java
        model_name = str(model.name())
        ok(f"Connected — model: '{model_name}'")
    except Exception as e:
        err(f"Cannot connect to COMSOL server: {e}")
        pipeline_result["status"] = "failed"
        pipeline_result["errors"].append(f"connect: {e}")
        return pipeline_result

    # ── STEP 3: GUI PAUSE ─────────────────────────────────────────────────
    gui_path = os.path.join(here, args.output)
    if not args.skip_gui_pause and not args.dry_run:
        banner("Step 3 / 6 — Manual GUI Steps", char="─")
        # Save model to known path so GUI can open it
        try:
            model.save(gui_path)
            ok(f"Model saved for GUI: {gui_path}")
        except Exception as e:
            warn(f"Pre-GUI save failed: {e}")
        gui_change_log = gui_watch_and_pause(gui_path, jm)
        # Verify the steps were done
        issues = verify_gui_steps(jm)
        if issues:
            for issue in issues:
                warn(issue)
            pipeline_result["warnings"].extend(issues)
            pipeline_result["steps"]["gui_pause"] = "done (warnings)"
        else:
            ok("GUI steps verified successfully")
            pipeline_result["steps"]["gui_pause"] = "done"
        pipeline_result["gui_change_log"] = gui_change_log
    else:
        ok("GUI pause skipped")
        pipeline_result["steps"]["gui_pause"] = "skipped"

    # Load recipe for auto-fixer
    try:
        with open(os.path.join(here, RECIPE_FILE)) as f:
            kb = json.load(f)
        recipe = kb[args.model_key]
        ok(f"Recipe loaded: '{args.model_key}'")
    except Exception as e:
        err(f"Cannot load recipe: {e}")
        pipeline_result["status"] = "failed"
        pipeline_result["errors"].append(f"recipe: {e}")
        return pipeline_result

    # ── STEP 4: VALIDATE ──────────────────────────────────────────────────
    banner("Step 4 / 6 — Validate 3D model", char="─")
    import comsol_validator
    import comsol_autofixer

    try:
        val_report = comsol_validator.validate_model(jm)
        comsol_validator.print_report(val_report)
        pipeline_result["steps"]["validate"] = val_report["status"]
        pipeline_result["validation"] = {
            "errors": val_report["errors"],
            "warnings": val_report["warnings"],
        }
    except Exception as e:
        err(f"Validation crashed: {e}")
        traceback.print_exc()
        val_report = {"status": "fail", "errors": [{"check": "crash", "detail": str(e)}],
                      "warnings": [], "info": []}
        pipeline_result["steps"]["validate"] = "crashed"

    # ── STEP 5: AUTO-FIX ──────────────────────────────────────────────────
    banner("Step 5 / 6 — Auto-fix", char="─")
    has_issues = val_report["errors"] or val_report["warnings"]

    if has_issues and not args.dry_run:
        try:
            fixed, final_report, fix_log = comsol_autofixer.autofix(
                jm, val_report, recipe, max_passes=3)
            comsol_autofixer.print_fix_log(fix_log)
            comsol_validator.print_report(final_report)
            pipeline_result["steps"]["autofix"] = f"{fixed} fixes applied"
            pipeline_result["final_validation"] = {
                "status": final_report["status"],
                "errors": final_report["errors"],
                "warnings": final_report["warnings"],
            }
            val_report = final_report
        except Exception as e:
            err(f"Auto-fix crashed: {e}")
            traceback.print_exc()
            pipeline_result["steps"]["autofix"] = "crashed"
    else:
        ok("No issues to fix" if not has_issues else "Dry-run — skipping fixes")
        pipeline_result["steps"]["autofix"] = "skipped"
        pipeline_result["final_validation"] = {
            "status": val_report["status"],
            "errors": val_report["errors"],
            "warnings": val_report["warnings"],
        }

    # Save model after fixes
    if not args.dry_run:
        try:
            out_path = os.path.join(here, args.output)
            model.save(out_path)
            ok(f"Model saved: {out_path}")
        except Exception as e:
            warn(f"Save failed: {e}")

    # ── STEP 6: RUN STUDY ─────────────────────────────────────────────────
    banner("Step 6 / 6 — Run Study", char="─")

    if val_report["status"] == "fail":
        warn("Validation still failing after fixes — skipping study run")
        warn("Fix remaining errors manually, then re-run with --skip-memorize --skip-convert")
        pipeline_result["steps"]["run_study"] = "skipped (validation failed)"
        pipeline_result["status"] = "partial"
    elif args.dry_run:
        ok("Dry-run — skipping study")
        pipeline_result["steps"]["run_study"] = "skipped (dry-run)"
        pipeline_result["status"] = "dry-run"
    else:
        study_tag = args.study

        # Create a plain stationary study if requested
        if args.create_stationary:
            try:
                # Pick a unique tag
                existing = [str(t) for t in list(jm.study().tags())]
                new_tag = "std_stat3d"
                i = 2
                while new_tag in existing:
                    new_tag = f"std_stat3d_{i}"
                    i += 1
                std = jm.study().create(new_tag)
                std.label("Stationary 3D (auto)")
                std.feature().create("stat", "Stationary")
                study_tag = new_tag
                ok(f"Created plain stationary study: '{new_tag}'")
            except Exception as e:
                err(f"Failed to create stationary study: {e}")
                study_tag = None

        if not study_tag:
            # Pick first available study
            try:
                all_std = [str(t) for t in list(jm.study().tags())]
                step(f"Available studies: {all_std}")
                study_tag = all_std[0] if all_std else None
            except Exception:
                study_tag = None

        if study_tag:
            ok_run, run_msg = run_study(jm, study_tag)
            pipeline_result["steps"]["run_study"] = "ok" if ok_run else "failed"
            if ok_run:
                # Save solved model
                try:
                    model.save(os.path.join(here, args.output))
                    ok("Solved model saved")
                except Exception as e:
                    warn(f"Save after solve failed: {e}")
            else:
                pipeline_result["errors"].append(f"study run: {run_msg}")
        else:
            warn("No studies found — skipping")
            pipeline_result["steps"]["run_study"] = "skipped (no studies)"

    # ── FINAL STATUS ──────────────────────────────────────────────────────
    banner("Pipeline Complete", char="═")

    all_ok = (
        val_report.get("status") == "pass"
        and not pipeline_result["errors"]
        and pipeline_result.get("status") not in ("failed",)
    )
    pipeline_result["status"] = "success" if all_ok else pipeline_result.get("status", "partial")

    print(f"\n  Status:  {pipeline_result['status'].upper()}")
    for sname, sval in pipeline_result["steps"].items():
        icon = "✓" if str(sval) in ("ok", "done", "skipped", "pass") else "⚠"
        print(f"  {icon}  {sname}: {sval}")

    if pipeline_result["errors"]:
        print("\n  Errors:")
        for e in pipeline_result["errors"]:
            print(f"    ✗ {e}")

    # Save to knowledge base
    save_knowledge(model_name, pipeline_result)

    return pipeline_result


# ── CLI ───────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="COMSOL AI Co-Pilot — autonomous 2D→3D pipeline"
    )
    parser.add_argument(
        "--model-key", default=MODEL_KEY,
        help="Recipe key (model name) in comsol_recipes.json"
    )
    parser.add_argument(
        "--output", default=OUTPUT_FILE,
        help=f"Output .mph filename (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "--study", default=None,
        help="Study tag to run (e.g. std3). If omitted, runs the first study."
    )
    parser.add_argument(
        "--mesh-size", type=int, default=5,
        help="COMSOL auto-mesh size 1 (fine) – 9 (coarse), default 5"
    )
    parser.add_argument(
        "--skip-memorize", action="store_true",
        help="Skip memorize step (use existing recipe)"
    )
    parser.add_argument(
        "--skip-convert", action="store_true",
        help="Skip convert step (use model already on server)"
    )
    parser.add_argument(
        "--skip-gui-pause", action="store_true",
        help="Skip the manual GUI pause (Thermodynamics steps)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run memorize+convert+validate only — no fixes or study run"
    )
    parser.add_argument(
        "--create-stationary", action="store_true",
        help="Create a new plain Stationary study and run it (ignores --study)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run_pipeline(args)
    sys.exit(0 if result.get("status") in ("success", "dry-run") else 1)
