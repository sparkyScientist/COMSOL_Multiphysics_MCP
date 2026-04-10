#!/usr/bin/env python
"""
comsol_validator.py — 3D Model Validator
==========================================
Inspects a COMSOL model directly via Java API and reports structural problems.

Checks:
  1. Active physics interfaces have non-empty domain selection
  2. Active physics features (user-added, non-default) have valid selections
  3. Active materials have non-empty domain selection
  4. Mesh is built with > 0 elements
  5. Active multiphysics couplings reference only active physics interfaces

Returns structured report:
  {
    "status": "pass" | "fail",
    "errors": [{"check": str, "detail": str}, ...],
    "warnings": [{"check": str, "detail": str}, ...],
    "info": [str, ...]
  }

Usage:
  # As module:
  import comsol_validator
  report = comsol_validator.validate_model(model_java)

  # Standalone:
  python comsol_validator.py
"""

import mph
import json
import os

COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment

# These feature types are COMSOL-managed defaults that don't have user-set
# selections — their domain/boundary coverage is determined automatically.
# Failing to set their selection is expected and harmless.
AUTO_DOMAIN_FEATURE_TYPES = {
    "FluidHeatTransferModel",   # fluid1 in HeatTransferInFluids — auto all-domain default
    "FluidProperties",           # fp1 in LaminarFlow / Turbulent Flow — auto all-domain default
    "init",                      # initial conditions (all domains)
    "ThermalInsulation",         # default thermal insulation
    "NoFlux",                    # default no-flux (Diluted Species)
    "WallBC",                    # default no-slip wall
    "ZeroFlux",
    "AxialSymmetry",             # skipped in 3D
    "Insulation",
    "PressureOutlet",
    "ConvectiveOutflow",         # COMSOL manages internally; selection.set() doesn't persist via API
    "Outflow",                   # same as ConvectiveOutflow in some physics
}

# Physics types where the interface-level selection is always "all domains"
# (COMSOL auto-assigns). Don't error if their top-level selection looks empty.
AUTO_ALL_DOMAIN_PHYSICS = {
    "SurfaceToSurfaceRadiation",  # rad applies to boundaries, not volumes
    "Chemistry",
    "ReactionEng",
}


def safe_str(val):
    try: return str(val)
    except: return "UNKNOWN"


def get_entities(node, preferred_dim=None):
    """
    Try to get selection entities from a node.
    Returns (dim, entity_list) or (-1, []) if nothing found.
    """
    try:
        sel = node.selection()
    except Exception:
        return -1, []

    dims_to_try = [preferred_dim] if preferred_dim is not None else []
    for d in [3, 2, 1, 0]:
        if d not in dims_to_try:
            dims_to_try.append(d)

    for dim in dims_to_try:
        try:
            ents = [int(i) for i in list(sel.entities(dim))]
            if ents:
                return dim, ents
        except Exception:
            continue
    return -1, []


def check_physics(jm, comp_tag, errors, warnings, info_log):
    """Check all active physics interfaces and their features."""
    info_log.append(f"--- Physics checks (comp: {comp_tag}) ---")
    try:
        comp = jm.component(comp_tag)
        phys_tags = [safe_str(t) for t in list(comp.physics().tags())]
    except Exception as e:
        errors.append({"check": "physics_access", "detail": f"Cannot list physics: {e}"})
        return

    active_physics_tags = set()

    for ptag in phys_tags:
        try:
            pnode = comp.physics(ptag)
            ptype = safe_str(pnode.getType())
            is_active = bool(pnode.isActive())

            if not is_active:
                info_log.append(f"  {ptag} ({ptype}): DISABLED — skip")
                continue

            active_physics_tags.add(ptag)
            info_log.append(f"  {ptag} ({ptype}): ACTIVE")

            # Check physics-level domain selection (only for domain physics)
            if ptype not in AUTO_ALL_DOMAIN_PHYSICS:
                dim, ents = get_entities(pnode, preferred_dim=3)
                if not ents:
                    warnings.append({
                        "check": "physics_domain_selection",
                        "detail": f"{ptag} ({ptype}): no domain selection found — may default to all domains"
                    })
                else:
                    info_log.append(f"    Domain selection: {ents} (dim={dim})")

            # Check each feature
            try:
                feat_tags = [safe_str(t) for t in list(pnode.feature().tags())]
            except Exception:
                continue

            for ftag in feat_tags:
                try:
                    fnode = pnode.feature(ftag)
                    ftype = safe_str(fnode.getType())
                    f_active = bool(fnode.isActive())

                    if not f_active:
                        continue  # disabled features are fine

                    if ftype in AUTO_DOMAIN_FEATURE_TYPES:
                        continue  # auto-managed, skip

                    # Check if feature has a non-empty selection
                    dim, ents = get_entities(fnode)
                    if not ents:
                        warnings.append({
                            "check": "physics_feature_selection",
                            "detail": f"{ptag}/{ftag} ({ftype}): active but selection is empty"
                        })
                    else:
                        info_log.append(f"    {ftag} ({ftype}): selection ok — {ents[:5]}{'...' if len(ents)>5 else ''} (dim={dim})")

                except Exception as e:
                    warnings.append({
                        "check": "physics_feature_access",
                        "detail": f"{ptag}/{ftag}: cannot inspect — {e}"
                    })

        except Exception as e:
            errors.append({"check": "physics_inspect", "detail": f"{ptag}: {e}"})

    return active_physics_tags


def check_materials(jm, comp_tag, errors, warnings, info_log):
    """Check that active materials have domain selections."""
    info_log.append("--- Material checks ---")
    try:
        comp = jm.component(comp_tag)
        mat_tags = [safe_str(t) for t in list(comp.material().tags())]
    except Exception as e:
        warnings.append({"check": "material_access", "detail": f"Cannot list materials: {e}"})
        return

    for mtag in mat_tags:
        try:
            mnode = comp.material(mtag)
            mtype = safe_str(mnode.getType())
            mlabel = safe_str(mnode.label())

            if mtype == "Switch":
                info_log.append(f"  {mtag} (Switch '{mlabel}'): Material Switch — requires GUI setup")
                warnings.append({
                    "check": "material_switch",
                    "detail": f"{mtag} ('{mlabel}'): Material Switch must be generated via Thermodynamics GUI"
                })
                continue

            is_active = bool(mnode.isActive())
            if not is_active:
                info_log.append(f"  {mtag} ('{mlabel}'): DISABLED — skip")
                continue

            # Check domain selection (materials should cover volumes = dim 3)
            dim, ents = get_entities(mnode, preferred_dim=3)
            if not ents:
                errors.append({
                    "check": "material_no_selection",
                    "detail": f"{mtag} ('{mlabel}'): active material has no domain selection — physics will have no material"
                })
            else:
                info_log.append(f"  {mtag} ('{mlabel}'): domains {ents} (dim={dim})")

        except Exception as e:
            warnings.append({"check": "material_inspect", "detail": f"{mtag}: {e}"})


def check_mesh(jm, comp_tag, errors, warnings, info_log):
    """Check that mesh is built and has elements."""
    info_log.append("--- Mesh checks ---")
    try:
        comp = jm.component(comp_tag)
        mesh_tags = [safe_str(t) for t in list(comp.mesh().tags())]
        if not mesh_tags:
            errors.append({"check": "mesh_missing", "detail": "No mesh sequence found"})
            return

        for mtag in mesh_tags:
            try:
                mesh = comp.mesh(mtag)
                is_built = False

                # Try isBuilt() — available in some COMSOL versions
                try:
                    is_built = bool(mesh.isBuilt())
                except Exception:
                    pass

                # Fallback: try to get vertices
                if not is_built:
                    try:
                        import numpy as np
                        vtx = np.array(mesh.getVertex())
                        is_built = vtx.shape[1] > 0
                    except Exception:
                        pass

                # Fallback: try stats
                if not is_built:
                    try:
                        stats = mesh.getNumElements()
                        is_built = int(stats) > 0
                    except Exception:
                        pass

                if is_built:
                    n_elem = "?"
                    try:
                        # Try different mesh element types
                        import numpy as np
                        total = 0
                        for etype in ["tet", "tri", "edg", "hex", "prism"]:
                            try:
                                elems = np.array(mesh.getElem(etype))
                                total += elems.shape[1] if len(elems.shape) > 1 else 0
                            except Exception:
                                pass
                        n_elem = total if total > 0 else "?"
                    except Exception:
                        pass
                    info_log.append(f"  {mtag}: built, ~{n_elem} elements")
                else:
                    errors.append({
                        "check": "mesh_not_built",
                        "detail": f"Mesh '{mtag}' is not built or has 0 elements"
                    })

            except Exception as e:
                errors.append({"check": "mesh_inspect", "detail": f"Mesh '{mtag}': {e}"})

    except Exception as e:
        errors.append({"check": "mesh_access", "detail": f"Cannot access mesh: {e}"})


def check_multiphysics(jm, comp_tag, active_physics_tags, errors, warnings, info_log):
    """Check active multiphysics couplings reference only active physics."""
    info_log.append("--- Multiphysics checks ---")
    if active_physics_tags is None:
        active_physics_tags = set()

    try:
        comp = jm.component(comp_tag)
        mp_tags = [safe_str(t) for t in list(comp.multiphysics().tags())]
    except Exception as e:
        warnings.append({"check": "multiphysics_access", "detail": f"Cannot list multiphysics: {e}"})
        return

    for mptag in mp_tags:
        try:
            mpnode = comp.multiphysics(mptag)
            mptype = safe_str(mpnode.getType())
            is_active = bool(mpnode.isActive())

            if not is_active:
                info_log.append(f"  {mptag} ({mptype}): DISABLED — skip")
                continue

            info_log.append(f"  {mptag} ({mptype}): ACTIVE")

            # Check physics references — look for physics1/physics2 properties
            try:
                props_to_check = ["physics1", "physics2", "spf", "ht", "tds", "tds2", "rad"]
                referenced = []
                for prop in props_to_check:
                    try:
                        val = safe_str(mpnode.getString(prop))
                        if val and val not in ("", "0", "CONVERSION_ERROR"):
                            # Extract just the physics tag (e.g. "spf" from "comp1/spf")
                            ref_tag = val.split("/")[-1]
                            if ref_tag:
                                referenced.append(ref_tag)
                    except Exception:
                        pass

                for ref in referenced:
                    if ref not in active_physics_tags:
                        # Check if it's even a known physics tag
                        try:
                            comp.physics(ref)
                            # If we can access it, it exists but is inactive
                            warnings.append({
                                "check": "multiphysics_inactive_ref",
                                "detail": f"{mptag} ({mptype}) references '{ref}' which is DISABLED"
                            })
                        except Exception:
                            pass  # ref might be a different property type

            except Exception:
                pass

        except Exception as e:
            warnings.append({"check": "multiphysics_inspect", "detail": f"{mptag}: {e}"})


def check_solver_compilation(jm, errors, warnings, info_log):
    """
    Light compilation check: try to create a solver study to catch variable errors.
    Creates then immediately removes a test solver.
    """
    info_log.append("--- Solver compilation check ---")
    test_tag = "sol_validator_test"
    try:
        sol = jm.sol().create(test_tag)
        # Try to attach it to first study
        try:
            study_tags = [safe_str(t) for t in list(jm.study().tags())]
            if study_tags:
                sol.study(study_tags[0])
                sol.attach(study_tags[0])
        except Exception:
            pass
        # Remove immediately
        try:
            jm.sol().remove(test_tag)
        except Exception:
            pass
        info_log.append("  Solver creation: OK")
    except Exception as e:
        err_str = str(e)
        if "variable is not compatible" in err_str or "variable" in err_str.lower():
            errors.append({
                "check": "solver_variable_conflict",
                "detail": f"Variable conflict detected: {err_str[:200]}"
            })
        else:
            warnings.append({
                "check": "solver_compilation",
                "detail": f"Solver test raised: {err_str[:200]}"
            })
        # Clean up
        try:
            jm.sol().remove(test_tag)
        except Exception:
            pass


def validate_model(jm, comp_tag="comp1"):
    """
    Validate a COMSOL 3D model (post-conversion).

    Args:
        jm: model.java (COMSOL Java model object)
        comp_tag: component tag, default "comp1"

    Returns:
        {
            "status": "pass" | "fail",
            "errors": [{"check": str, "detail": str}, ...],
            "warnings": [{"check": str, "detail": str}, ...],
            "info": [str, ...]
        }
    """
    errors = []
    warnings = []
    info_log = []

    info_log.append(f"Validating model: comp='{comp_tag}'")

    # 1. Physics checks
    active_physics = check_physics(jm, comp_tag, errors, warnings, info_log)

    # 2. Material checks
    check_materials(jm, comp_tag, errors, warnings, info_log)

    # 3. Mesh checks
    check_mesh(jm, comp_tag, errors, warnings, info_log)

    # 4. Multiphysics checks
    check_multiphysics(jm, comp_tag, active_physics or set(), errors, warnings, info_log)

    # 5. Solver compilation check
    check_solver_compilation(jm, errors, warnings, info_log)

    status = "fail" if errors else "pass"
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info_log,
    }


def print_report(report):
    """Pretty-print the validation report."""
    status = report["status"]
    n_err = len(report["errors"])
    n_warn = len(report["warnings"])

    print("\n" + "═" * 68)
    print(f"  VALIDATION REPORT — {'✓ PASS' if status == 'pass' else '✗ FAIL'}")
    print("═" * 68)

    print(f"\n  Errors:   {n_err}")
    print(f"  Warnings: {n_warn}")

    if report["errors"]:
        print("\n  ── ERRORS ──────────────────────────────────────────────────")
        for e in report["errors"]:
            print(f"  ✗ [{e['check']}]")
            print(f"    {e['detail']}")

    if report["warnings"]:
        print("\n  ── WARNINGS ────────────────────────────────────────────────")
        for w in report["warnings"]:
            print(f"  ⚠ [{w['check']}]")
            print(f"    {w['detail']}")

    print("\n  ── INFO LOG ────────────────────────────────────────────────")
    for line in report["info"]:
        print(f"  {line}")

    print("\n" + "═" * 68)
    print(f"  Status: {status.upper()}")
    print("═" * 68)


# ── STANDALONE RUNNER ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 68)
    print("  COMSOL 3D Model Validator")
    print("=" * 68)

    client = mph.Client(port=COMSOL_PORT)
    models = client.models()

    if not models:
        print("  No models loaded on server. Load a model first.")
        sys.exit(1)

    # Use the most recently loaded model
    model = models[-1]
    model_name = str(model.name())
    print(f"  Model: '{model_name}'")

    report = validate_model(model.java)
    print_report(report)

    # Save report to JSON
    report_file = "comsol_validation_report.json"
    with open(report_file, "w") as f:
        json.dump({"model": model_name, **report}, f, indent=2)
    print(f"\n  Report saved to: {report_file}")

    sys.exit(0 if report["status"] == "pass" else 1)
