#!/usr/bin/env python
"""
comsol_autofixer.py — Auto-Fix Engine for 3D Model Conversion Errors
======================================================================
Takes a validation report (from comsol_validator.py) and attempts to fix
each reported error automatically.

Fix functions:
  fix_empty_feature_selection   — re-run CylinderSelectionMapper for empty BCs
  fix_material_no_selection     — assign unassigned materials to remaining domains
  fix_multiphysics_inactive_ref — disable multiphysics that ref inactive physics

Usage:
  import comsol_autofixer
  fixed, report = comsol_autofixer.autofix(model_java, validation_report, recipe)
"""

import json

# ── HELPERS ───────────────────────────────────────────────────────────────

def safe_str(val):
    try: return str(val)
    except: return "UNKNOWN"


def _get_entities(node, preferred_dim=None):
    """Try to get selection entities from a node. Returns (dim, list)."""
    try:
        sel = node.selection()
    except Exception:
        return -1, []
    dims = [preferred_dim] if preferred_dim is not None else []
    for d in [3, 2, 1, 0]:
        if d not in dims:
            dims.append(d)
    for dim in dims:
        try:
            ents = [int(i) for i in list(sel.entities(dim))]
            if ents:
                return dim, ents
        except Exception:
            continue
    return -1, []


class CylinderMapper:
    """
    Lightweight re-implementation of CylinderSelectionMapper for use in the
    auto-fixer. Same algorithm as the converter — creates temporary Cylinder
    selections to find 3D entities that correspond to 2D coord ranges.
    """
    def __init__(self, jm, comp_tag, boundary_map, domain_map):
        self.jm = jm
        self.comp_tag = comp_tag
        self.boundary_map = boundary_map  # {str_idx: {r_min, r_max, z_min, z_max, is_axial, ...}}
        self.domain_map = domain_map      # {str_idx: {r_min, r_max, z_min, z_max}}
        self._counter = 0
        self._tol = 5e-5

    def _temp_tag(self):
        self._counter += 1
        return f"_autofix_cyl_{self._counter}"

    def _find_cylinder(self, r_min, r_max, z_min, z_max, entity_dim):
        """Create a Cylinder selector and return matching entity indices."""
        tol = self._tol
        if abs(z_max - z_min) < 1e-6:
            z_min -= tol; z_max += tol
        tag = self._temp_tag()
        comp = self.jm.component(self.comp_tag)
        try:
            sel = comp.selection().create(tag, "Cylinder")
            sel.set("entitydim", str(entity_dim))
            sel.set("r", str(r_max + tol))
            sel.set("rin", str(max(0, r_min - tol)))
            sel.set("top", str(z_max + tol))
            sel.set("bottom", str(z_min - tol))
            sel.set("pos", ["0", "0", "0"])
            sel.set("axis", ["0", "0", "1"])
            sel.set("condition", "inside")
            ents = [int(i) for i in list(sel.entities(entity_dim))]
            if not ents:
                sel.set("condition", "intersects")
                ents = [int(i) for i in list(sel.entities(entity_dim))]
            try: comp.selection().remove(tag)
            except Exception: pass
            return ents
        except Exception:
            try: comp.selection().remove(tag)
            except Exception: pass
            return []

    def map_boundaries(self, indices_2d):
        """Map 2D boundary indices to 3D boundary (surface) indices."""
        all_idx = set()
        for idx in indices_2d:
            bdata = self.boundary_map.get(str(idx), {})
            if not bdata: continue
            if bdata.get("is_axial", False): continue  # skip axial
            ents = self._find_cylinder(
                bdata.get("r_min", 0), bdata.get("r_max", 0),
                bdata.get("z_min", 0), bdata.get("z_max", 0),
                entity_dim=2
            )
            all_idx.update(ents)
        return sorted(all_idx)

    def map_domains(self, indices_2d):
        """Map 2D domain indices to 3D volume indices."""
        all_idx = set()
        for idx in indices_2d:
            ddata = self.domain_map.get(str(idx), {})
            if not ddata: continue
            ents = self._find_cylinder(
                ddata.get("r_min", 0), ddata.get("r_max", 0),
                ddata.get("z_min", 0), ddata.get("z_max", 0),
                entity_dim=3
            )
            all_idx.update(ents)
        return sorted(all_idx)


# ── FIX FUNCTIONS ─────────────────────────────────────────────────────────

def fix_empty_feature_selection(jm, comp_tag, phys_tag, feat_tag,
                                 indices_2d, entity_dim_hint,
                                 mapper, log):
    """
    Re-attempt selection mapping for a physics feature with empty selection.

    Args:
        jm: model.java
        comp_tag: e.g. "comp1"
        phys_tag: e.g. "ht"
        feat_tag: e.g. "ofl1"
        indices_2d: 2D entity indices from the recipe
        entity_dim_hint: 1 for boundary, 2 for domain (from recipe)
        mapper: CylinderMapper instance
        log: list to append log messages

    Returns True if fix was applied.
    """
    try:
        comp = jm.component(comp_tag)
        feat_node = comp.physics(phys_tag).feature(feat_tag)
    except Exception as e:
        log.append(f"  ✗ {phys_tag}/{feat_tag}: cannot access — {e}")
        return False

    if entity_dim_hint <= 1:
        mapped = mapper.map_boundaries(indices_2d)
    else:
        mapped = mapper.map_domains(indices_2d)

    if not mapped:
        log.append(f"  ✗ {phys_tag}/{feat_tag}: Cylinder mapper returned empty for 2D {indices_2d}")
        return False

    try:
        feat_node.selection().set(mapped)
        log.append(f"  ✓ {phys_tag}/{feat_tag}: selection set to {mapped} (2D {indices_2d} → 3D)")
        return True
    except Exception as e:
        log.append(f"  ✗ {phys_tag}/{feat_tag}: selection.set({mapped}) failed — {e}")
        return False


def fix_material_no_selection(jm, comp_tag, mat_tag, indices_2d, mapper, log):
    """
    Assign a material to domains via CylinderMapper.

    Args:
        jm: model.java
        comp_tag: e.g. "comp1"
        mat_tag: e.g. "mat5"
        indices_2d: 2D domain indices from the recipe
        mapper: CylinderMapper instance
        log: list to append log messages

    Returns True if fix was applied.
    """
    try:
        comp = jm.component(comp_tag)
        mat_node = comp.material(mat_tag)
    except Exception as e:
        log.append(f"  ✗ {mat_tag}: cannot access — {e}")
        return False

    mapped = mapper.map_domains(indices_2d)
    if not mapped:
        log.append(f"  ✗ {mat_tag}: Cylinder mapper returned empty for 2D domains {indices_2d}")
        return False

    try:
        mat_node.selection().set(mapped)
        log.append(f"  ✓ {mat_tag}: domain selection set to {mapped} (2D {indices_2d} → 3D)")
        return True
    except Exception as e:
        log.append(f"  ✗ {mat_tag}: selection.set({mapped}) failed — {e}")
        return False


def fix_multiphysics_inactive_ref(jm, comp_tag, mp_tag, log):
    """
    Disable a multiphysics coupling that references inactive physics.

    Args:
        jm: model.java
        comp_tag: e.g. "comp1"
        mp_tag: e.g. "rfd1"
        log: list to append log messages

    Returns True if fix was applied.
    """
    try:
        comp = jm.component(comp_tag)
        mpnode = comp.multiphysics(mp_tag)
    except Exception as e:
        log.append(f"  ✗ {mp_tag}: cannot access — {e}")
        return False

    try:
        mpnode.active(False)
        log.append(f"  ✓ {mp_tag}: disabled (referenced inactive physics)")
        return True
    except Exception as e:
        log.append(f"  ✗ {mp_tag}: active(False) failed — {e}")
        return False


def fix_unbuilt_mesh(jm, comp_tag, mesh_size, log):
    """
    Rebuild the mesh if it failed.

    Args:
        jm: model.java
        comp_tag: e.g. "comp1"
        mesh_size: COMSOL auto-mesh size (1=extra fine, 9=extra coarse)
        log: list to append log messages

    Returns True if mesh was rebuilt.
    """
    try:
        comp = jm.component(comp_tag)
        mesh_tags = [safe_str(t) for t in list(comp.mesh().tags())]
        if not mesh_tags:
            # Create a new mesh sequence
            geom_tags = [safe_str(t) for t in list(comp.geom().tags())]
            geom_tag = geom_tags[0] if geom_tags else "geom1"
            jm.mesh().create("mesh1", geom_tag)
            mesh_tags = ["mesh1"]

        mesh = comp.mesh(mesh_tags[0])
        mesh.autoMeshSize(mesh_size)
        mesh.run()
        log.append(f"  ✓ Mesh rebuilt (size={mesh_size})")
        return True
    except Exception as e:
        log.append(f"  ✗ Mesh rebuild failed: {e}")
        return False


# ── MAIN AUTOFIX ENTRY POINT ──────────────────────────────────────────────

def autofix(jm, validation_report, recipe, comp_tag="comp1", mesh_size=5, max_passes=3):
    """
    Attempt to auto-fix errors and warnings from the validation report.

    Args:
        jm: model.java
        validation_report: dict from comsol_validator.validate_model()
        recipe: dict loaded from comsol_recipes.json for the model
        comp_tag: component tag, default "comp1"
        mesh_size: COMSOL auto-mesh size for mesh rebuilds (default 5)
        max_passes: max fix-validate cycles (default 3)

    Returns:
        (fixed_count, final_report)
        Where final_report is the last validation_report after fixes.
    """
    import comsol_validator

    log = []
    fixed_total = 0

    # Build mapper from recipe coord maps
    comp_data = recipe.get("components", {}).get(comp_tag, {})
    boundary_map = comp_data.get("boundary_coord_map", {})
    domain_map = comp_data.get("domain_coord_map", {})
    mapper = CylinderMapper(jm, comp_tag, boundary_map, domain_map)

    # Build index: phys_tag/feat_tag → recipe data for fast lookup
    feat_index = {}  # (phys_tag, feat_tag) → {selection_indices, entity_dimension}
    for ptag, pdata in comp_data.get("physics", {}).items():
        for fd in pdata.get("features", []):
            ftag = fd.get("tag", "")
            if ftag:
                feat_index[(ptag, ftag)] = {
                    "selection_indices": fd.get("selection_indices", []),
                    "entity_dimension": fd.get("entity_dimension", -1),
                }

    # Build material index: mat_tag → {selection_indices}
    mat_index = {}
    for md in comp_data.get("materials", []):
        mtag = md.get("tag", "")
        if mtag:
            mat_index[mtag] = {
                "selection_indices": md.get("selection_indices", []),
            }

    report = validation_report
    already_attempted = set()  # track (check, detail) pairs so we don't retry unfixable items

    for pass_num in range(1, max_passes + 1):
        errors = report.get("errors", [])
        warnings = report.get("warnings", [])

        if not errors and not warnings:
            log.append(f"Pass {pass_num}: Nothing to fix — done.")
            break

        pass_fixed = 0
        log.append(f"\n=== Auto-fix pass {pass_num} ===")

        for item in errors + warnings:
            check = item.get("check", "")
            detail = item.get("detail", "")
            attempt_key = (check, detail[:60])
            if attempt_key in already_attempted:
                log.append(f"  ↩ skip (already attempted, not fixable): [{check}]")
                continue
            already_attempted.add(attempt_key)

            # ── Fix: empty physics feature selection ──────────────────────
            if check == "physics_feature_selection":
                # Parse "phys_tag/feat_tag (type): message"
                try:
                    path = detail.split(":")[0].strip()  # e.g. "ht/ofl1 (ConvectiveOutflow)"
                    path = path.split("(")[0].strip()     # e.g. "ht/ofl1"
                    ptag, ftag = path.split("/")
                    recipe_data = feat_index.get((ptag, ftag), {})
                    indices_2d = recipe_data.get("selection_indices", [])
                    dim_hint = recipe_data.get("entity_dimension", 1)
                    if indices_2d:
                        ok = fix_empty_feature_selection(
                            jm, comp_tag, ptag, ftag, indices_2d, dim_hint, mapper, log)
                        if ok: pass_fixed += 1
                    else:
                        log.append(f"  ⚠ {ptag}/{ftag}: no 2D indices in recipe — cannot remap")
                except Exception as e:
                    log.append(f"  ✗ parse error for feature fix: {e} — {detail}")

            # ── Fix: material with no domain selection ────────────────────
            elif check == "material_no_selection":
                try:
                    mtag = detail.split("(")[0].strip()
                    indices_2d = mat_index.get(mtag, {}).get("selection_indices", [])
                    if indices_2d:
                        ok = fix_material_no_selection(
                            jm, comp_tag, mtag, indices_2d, mapper, log)
                        if ok: pass_fixed += 1
                    else:
                        log.append(f"  ⚠ {mtag}: no 2D domain indices in recipe")
                except Exception as e:
                    log.append(f"  ✗ parse error for material fix: {e} — {detail}")

            # ── Fix: multiphysics references inactive physics ──────────────
            elif check == "multiphysics_inactive_ref":
                try:
                    # "rfd1 (ReactingFlowDS) references 'tds' which is DISABLED"
                    mp_tag = detail.split("(")[0].strip()
                    ok = fix_multiphysics_inactive_ref(jm, comp_tag, mp_tag, log)
                    if ok: pass_fixed += 1
                except Exception as e:
                    log.append(f"  ✗ parse error for multiphysics fix: {e} — {detail}")

            # ── Fix: mesh not built ───────────────────────────────────────
            elif check in ("mesh_not_built", "mesh_missing"):
                ok = fix_unbuilt_mesh(jm, comp_tag, mesh_size, log)
                if ok: pass_fixed += 1

            # ── Fix: solver variable conflict ─────────────────────────────
            elif check == "solver_variable_conflict":
                log.append(f"  ⚠ Variable conflict requires manual fix: {detail[:100]}")
                log.append(f"    Check: disabled multiphysics still referencing active physics vars")

        fixed_total += pass_fixed
        log.append(f"Pass {pass_num}: fixed {pass_fixed} items")

        if pass_fixed == 0:
            log.append("No more fixes applied — stopping.")
            break

        # Re-validate
        log.append("Re-validating...")
        report = comsol_validator.validate_model(jm, comp_tag)
        if report["status"] == "pass" and not report.get("warnings"):
            log.append("✓ Clean pass — all issues resolved.")
            break

    return fixed_total, report, log


def print_fix_log(log):
    print("\n" + "─" * 68)
    print("  AUTO-FIX LOG")
    print("─" * 68)
    for line in log:
        print(f"  {line}")
    print("─" * 68)


# ── STANDALONE RUNNER ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys
    import mph
    import comsol_validator

    COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment
    RECIPE_FILE = "comsol_recipes.json"
    MODEL_KEY = os.getenv("COMSOL_MODEL_KEY", "")  # configured via config.py / environment — set to your model's recipe key

    print("=" * 68)
    print("  COMSOL Auto-Fixer")
    print("=" * 68)

    client = mph.Client(port=COMSOL_PORT)
    models = client.models()
    if not models:
        print("  No models loaded on server.")
        sys.exit(1)

    model = models[-1]
    print(f"  Model: '{model.name()}'")

    with open(RECIPE_FILE) as f:
        kb = json.load(f)
    recipe = kb[MODEL_KEY]

    # Run initial validation
    print("\n  Running initial validation...")
    report = comsol_validator.validate_model(model.java)
    comsol_validator.print_report(report)

    if report["status"] == "pass" and not report.get("warnings"):
        print("\n  Model already clean — no fixes needed.")
        sys.exit(0)

    # Run auto-fix
    print("\n  Running auto-fix...")
    fixed, final_report, fix_log = autofix(model.java, report, recipe)
    print_fix_log(fix_log)

    print(f"\n  Fixed {fixed} items total.")
    print("\n  Final validation:")
    comsol_validator.print_report(final_report)

    # Save report
    out = {
        "model": str(model.name()),
        "fix_log": fix_log,
        "fixes_applied": fixed,
        **final_report,
    }
    with open("comsol_autofix_report.json", "w") as f:
        json.dump(out, f, indent=2)
    print("  Report saved to: comsol_autofix_report.json")

    sys.exit(0 if final_report["status"] == "pass" else 1)
