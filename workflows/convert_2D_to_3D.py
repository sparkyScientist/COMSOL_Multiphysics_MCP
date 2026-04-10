#!/usr/bin/env python
"""
convert_2D_to_3D.py v10.0 — Direct 3D Cylinders (No Revolve)
==============================================================
v10: Recipe-driven active state. The memorizer (v12) captures isActive()
for every physics, feature, multiphysics, study step, material, function,
and coupling. The converter now respects those states instead of hardcoding.

A 2D axisymmetric rectangle at r=[r1,r2], z=[z1,z2] becomes:
  - If r1 == 0: a solid Cylinder(radius=r2, height=z2-z1) at z=z1
  - If r1 > 0:  Cylinder(radius=r2) - Cylinder(radius=r1) (boolean difference)

This gives clean single surfaces for inlet/outlet/wall selections.
"""

import mph
import json
import os
import sys
import traceback

RECIPE_FILE = "comsol_recipes.json"
MODEL_KEY = os.getenv("COMSOL_MODEL_KEY", "")  # configured via config.py / environment — set to your model's recipe key
OUTPUT_FILE = os.getenv("COMSOL_OUTPUT_FILE", "output_3D.mph")  # configured via config.py / environment
COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment
MESH_SIZE = 8  # coarse for convergence testing (was 5)

# ── CONVERGENCE TEST FLAGS ────────────────────────────────────────────────
# Set DISABLE_RADIATION=True to skip rad + htrad1 for a faster first solve.
# Re-enable once flow+heat converges (use that solution as initial condition).
DISABLE_RADIATION = True

SKIP_PROPERTIES = {
    "buildcount", "buildtime", "buildinfox", "buildinfo",
    "selresult", "selresultshow", "color", "customcolor",
    "sellayer", "sellayershow", "contributeto",
    "geomattr", "geomattrlevel", "arrowdispl", "arrowint",
    "labelpos", "sizeconstr", "posconstr", "rotconstr",
    "layerold", "layernameold", "StudyStep", "showPhysicsSymbols",
    "pairContrib", "cumselkey", "buildmessage",
}
AXISYMMETRY_TYPES = {"AxialSymmetry"}
SKIP_IN_3D = {"AxialSymmetry", "OpenBoundary"}

def banner(msg):
    print("\n" + "═" * 68)
    print(f"  {msg}")
    print("═" * 68)

def info(msg): print(f"  ▸ {msg}")
def warn(msg): print(f"  ⚠ {msg}")

def safe_set(node, key, value):
    try:
        if isinstance(value, list): node.set(key, value)
        else: node.set(key, str(value))
    except: pass

def flatten_value(value):
    if isinstance(value, list):
        return value[0] if len(value) == 1 else ", ".join(str(v) for v in value)
    return str(value)

def filter_properties(props):
    return {k: v for k, v in props.items()
            if k not in SKIP_PROPERTIES
            and not (isinstance(v, list) and len(v) == 0)
            and not (isinstance(v, str) and v == "")}

def guess_dim_2d(feat_type):
    boundary = {"InletBoundary", "OutletBoundary", "WallBC", "OpenBoundary",
        "TemperatureBoundary", "HeatFlux", "Inflow", "Outflow",
        "ConvectiveOutflow", "NoFlux", "DiffuseSurface", "OpaqueSurface",
        "ThermalInsulation", "Continuity", "IsothermalDomainInterface",
        "LocalThermalNonequilibriumBoundary"}
    domain = {"FluidProperties", "SolidHeatTransferModel", "FluidHeatTransferModel",
        "SpeciesProperties", "Fluid", "Reactions", "Gravity"}
    return 1 if feat_type in boundary else (2 if feat_type in domain else 1)


# ═══════════════════════════════════════════════════════════════════════
# DIRECT 3D GEOMETRY (No Revolve)
# ═══════════════════════════════════════════════════════════════════════

def create_3d_geometry_direct(jm, recipe):
    """
    Convert 2D axisymmetric rectangles directly to 3D cylinders.
    
    Each 2D Rectangle at pos=[r_off, z_off] with size=[lx, ly]:
      - r range: [r_off, r_off + lx]  (or centered, depending on 'base')
      - z range: [z_off, z_off + ly]
    
    In 3D:
      - Create Cylinder with radius = r_off + lx, height = ly
      - Position at z = z_off (along the z-axis)
      - If r_off > 0, subtract inner cylinder (boolean difference)
    
    The z-axis in 2D becomes the z-axis in 3D.
    """
    banner("3D Geometry (Direct Cylinders)")
    
    comp_data = recipe["components"]["comp1"]
    geom_features = comp_data.get("geometry", {}).get("geom1", [])
    
    geom = jm.geom().create("geom1", 3)
    
    cyl_count = 0
    
    for feat in geom_features:
        tag = feat.get("tag", "")
        ftype = feat.get("type", "")
        props = feat.get("properties", {})
        
        if ftype != "Rectangle":
            if ftype not in ("Finalize", "FormUnion"):
                info(f"Skipping non-rectangle: {tag} ({ftype})")
            continue
        
        # Extract rectangle parameters
        # lx = radial width, ly = axial height
        lx = props.get("lx", "0")
        ly = props.get("ly", "0")
        pos = props.get("pos", ["0", "0"])
        base = props.get("base", "corner")
        
        if isinstance(pos, str):
            pos = [p.strip() for p in pos.split(",")]
        
        # pos[0] = r offset, pos[1] = z offset
        r_off = pos[0] if len(pos) > 0 else "0"
        z_off = pos[1] if len(pos) > 1 else "0"
        
        # Outer radius = r_off + lx (for corner base)
        outer_r = f"({r_off})+({lx})" if r_off != "0" else lx
        inner_r = r_off
        height = ly
        
        cyl_count += 1
        cyl_tag = f"cyl{cyl_count}"
        
        info(f"  {tag} → {cyl_tag}: r_outer={outer_r}, height={height}, z_pos={z_off}")
        
        try:
            cyl = geom.feature().create(cyl_tag, "Cylinder")
            cyl.set("r", str(outer_r))
            cyl.set("h", str(height))
            # Position: cylinder base at z_off, centered at x=0, y=0
            cyl.set("pos", ["0", "0", str(z_off)])
            # Axis along z (default)
            cyl.set("axis", ["0", "0", "1"])
            
            info(f"    ✓ Cylinder created")
            
        except Exception as e:
            warn(f"    Failed: {e}")
    
    # Build geometry (FormUnion will merge overlapping cylinders)
    info("Building geometry (FormUnion)...")
    try:
        jm.geom("geom1").run()
        n_dom = int(geom.getNDomains())
        n_bnd = int(geom.getNBoundaries())
        info(f"✓ Built: {n_dom} domains, {n_bnd} boundaries")
    except Exception as e:
        warn(f"Build failed: {e}")
    
    return geom


# ═══════════════════════════════════════════════════════════════════════
# CYLINDER SELECTION MAPPER
# ═══════════════════════════════════════════════════════════════════════

class CylinderSelectionMapper:
    def __init__(self, model_java, geom_tag, boundary_map, domain_map):
        self.jm = model_java
        self.geom_tag = geom_tag
        self.boundary_map = boundary_map
        self.domain_map = domain_map
        self._sel_counter = 0
        try:
            geom = self.jm.geom(geom_tag)
            info(f"3D geometry: {geom.getNDomains()} domains, {geom.getNBoundaries()} boundaries")
        except: pass
    
    def map_boundaries(self, indices_2d):
        if not indices_2d: return []
        regions, skipped = [], []
        for idx in indices_2d:
            bdata = self.boundary_map.get(str(idx), {})
            if not bdata: continue
            if bdata.get("is_axial", False):
                skipped.append(idx); continue
            regions.append((idx, bdata))
        if skipped: info(f"      Skipped axial: {skipped}")
        return self._find(regions, 2) if regions else []
    
    def map_domains(self, indices_2d):
        if not indices_2d: return []
        regions = [(i, self.domain_map[str(i)]) for i in indices_2d if str(i) in self.domain_map]
        return self._find(regions, 3) if regions else []
    
    def _find(self, regions, entity_dim):
        all_idx = set()
        comp = self.jm.component("comp1")
        tol = 5e-5
        
        for idx_2d, region in regions:
            self._sel_counter += 1
            tag = f"_cyl_{self._sel_counter}"
            r_min = region.get("r_min", 0)
            r_max = region.get("r_max", 0)
            z_min = region.get("z_min", 0)
            z_max = region.get("z_max", 0)
            
            # Thin slab for single-z
            if abs(z_max - z_min) < 1e-6:
                z_min -= tol; z_max += tol
            
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
                
                try:
                    ents = [int(i) for i in list(sel.entities(entity_dim))]
                    if not ents:
                        sel.set("condition", "intersects")
                        ents = [int(i) for i in list(sel.entities(entity_dim))]
                    all_idx.update(ents)
                except: pass
                
                try: comp.selection().remove(tag)
                except: pass
            except Exception as e:
                try: comp.selection().remove(tag)
                except: pass
        
        return sorted(all_idx)
    
    def apply_selection(self, feat_node, indices_2d, entity_dim_hint):
        if not indices_2d: return False
        indices_3d = self.map_boundaries(indices_2d) if entity_dim_hint <= 1 else self.map_domains(indices_2d)
        if not indices_3d: return False
        try:
            feat_node.selection().set(indices_3d)
            return True
        except: return False


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# MATERIALS (including Material Switch for gas compositions)
# ═══════════════════════════════════════════════════════════════════════

def create_materials(jm, recipe, mapper):
    banner("Materials")
    comp_data = recipe["components"]["comp1"]
    comp_node = jm.component("comp1")
    mat_recipes = comp_data.get("materials", [])
    
    GAS_PROPS = {
        "density": "Densitypp1(T,pA,{xm1},{xm2},{xm3},{xm4})",
        "heatcapacity": "HeatCapacityCppp1(T,pA,{xm1},{xm2},{xm3},{xm4})",
        "ratioofspecificheat": "HeatCapacityRatioCpCvpp1(T,pA,{xm1},{xm2},{xm3},{xm4})",
        "thermalconductivity": "ThermalConductivitypp1(T,pA,{xm1},{xm2},{xm3},{xm4})",
        "dynamicviscosity": "Viscositypp1(T,pA,{xm1},{xm2},{xm3},{xm4})",
    }
    
    GAS_COMPS = [
        ("pp1mat1", "61He 36.5H2 2.5CH4", "0.61", "0.365", "0.025", "0.0"),
        ("pp1mat2", "97.5H2 2.5CH4", "0", "0.975", "0.025", "0.0"),
        ("pp1mat5", "10N2 51He 36.5H2 2.5CH4", "0.51", "0.365", "0.025", "0.10"),
        ("pp1mat4", "31N2 30He H2 2.5CH4", "0.3", "0.365", "0.025", "0.31"),
        ("pp1mat3", "61N2 36.5H2 2.5CH4", "0", "0.365", "0.025", "0.61"),
    ]
    
    for md in mat_recipes:
        mtag, mtype, mlabel = md.get("tag",""), md.get("type",""), md.get("label","")
        sel_idx = md.get("selection_indices", [])
        
        if mtype == "Switch":
            info(f"SKIP Material Switch '{mtag}' — must be generated from Thermodynamics GUI")
            info(f"  After opening in COMSOL GUI:")
            info(f"  1. Right-click Thermodynamic System 1 (pp1) → Define System")
            info(f"  2. Right-click pp1 → Generate Material")
            info(f"  3. Set mole fractions for each gas composition")
            info(f"  Gas compositions needed:")
            for ctag, clabel, xm1, xm2, xm3, xm4 in GAS_COMPS:
                info(f"    {clabel}: He={xm1}, H2={xm2}, CH4={xm3}, N2={xm4}")
        
        elif mtype == "Common":
            # Skip inactive materials (active state from recipe)
            if not md.get("active", True):
                info(f"SKIP inactive mat '{mtag}' ({mlabel})")
                continue
            info(f"Creating '{mtag}' ({mlabel})...")
            try:
                mat = comp_node.material().create(mtag, "Common")
                mat.label(mlabel)
                # Set property groups (thermal conductivity, density, etc.)
                pgs = md.get("property_groups", {})
                for pgt, pgd in pgs.items():
                    pg_props = pgd.get("properties", {})
                    try:
                        pg = mat.propertyGroup(pgt)
                    except:
                        try: pg = mat.propertyGroup().create(pgt, pgt)
                        except: continue
                    skip_pg = {"INFO_PREFIX","LocalProperties","LocalDescrName"}
                    for k, v in pg_props.items():
                        if k in skip_pg or not v or v == "0" or v == "": continue
                        try: pg.set(k, str(v))
                        except: pass
                    info(f"  pg '{pgt}': {len(pg_props)} props")
                # Apply selection — materials always go on domains (dim=2 in 2D → map_domains)
                # sel_dim from 2D model may be 1 (boundary) due to mesh artifact; always use domain mapping
                if sel_idx:
                    mapped = mapper.map_domains(sel_idx)
                    if mapped:
                        try:
                            mat.selection().set(mapped)
                            info(f"  selection: 2D domains {sel_idx} → 3D {mapped}")
                        except Exception as se:
                            warn(f"  selection set failed: {se}")
                    else:
                        warn(f"  selection: could not map 2D {sel_idx} to 3D domains")
                info(f"  ✓ Created")
            except Exception as e:
                warn(f"  Failed: {e}")


def main():
    print("\n" + "█" * 68)
    print("██  COMSOL 2D→3D v10.0 (Recipe-Driven Active State)")
    print("█" * 68)
    
    # Load recipe
    banner("Loading Recipe")
    with open(RECIPE_FILE) as f:
        kb = json.load(f)
    recipe = kb[MODEL_KEY]
    comp_data = recipe["components"]["comp1"]
    defs = comp_data.get("definitions", {})
    
    info(f"Parameters: {len(recipe.get('parameters', {}))}")
    info(f"Physics: {len(comp_data.get('physics', {}))}")
    info(f"Boundary map: {len(comp_data.get('boundary_coord_map', {}))} entries")
    info(f"Domain map: {len(comp_data.get('domain_coord_map', {}))} entries")
    
    # Connect
    banner("Connecting")
    client = mph.Client(port=COMSOL_PORT)
    info("✓ Connected")
    
    # Create model
    banner("Creating Model")
    model = client.create("shelly_3D_v8")
    jm = model.java
    comp = jm.component().create("comp1", True)
    
    # Parameters
    banner("Parameters")
    for name, data in recipe.get("parameters", {}).items():
        try: jm.param().set(name, data["expression"], data.get("description", ""))
        except: pass
    info(f"✓ {len(recipe['parameters'])} set")
    
    # 3D Geometry — DIRECT CYLINDERS
    geom = create_3d_geometry_direct(jm, recipe)
    
    # Definitions
    banner("Definitions")
    comp_node = jm.component("comp1")
    
    for vd in defs.get("variables", []):
        vtag = vd.get("tag", "")
        if not vtag: continue
        try:
            vn = comp_node.variable().create(vtag)
            for vname, vinfo in vd.get("variables", {}).items():
                if vinfo.get("expression"):
                    vn.set(vname, vinfo["expression"], vinfo.get("description", ""))
            info(f"  var '{vtag}': {len(vd.get('variables', {}))} entries")
        except Exception as e: warn(f"  var {vtag}: {e}")
    
    # --- Functions (two-layer disable: recipe + 3D safety rules) ---
    # Layer 1: Recipe active state (from memorizer)
    # Layer 2: builder_* functions ALWAYS disabled in 3D — they reference
    #          thermo internals that cause "Unknown file" / res23 errors
    func_created, func_disabled = 0, 0
    for fd in defs.get("functions", []):
        ftag, ftype = fd.get("tag",""), fd.get("type","")
        if not ftag or not ftype: continue
        try:
            fn = comp_node.func().create(ftag, ftype)
            
            # Force interpolation to use local table, not file
            if ftype == "Interpolation":
                fn.set("source", "table")
            
            for k, v in filter_properties(fd.get("properties", {})).items():
                if k == "table": continue
                safe_set(fn, k, flatten_value(v))
            table_data = fd.get("table_data")
            if table_data and ftype == "Interpolation":
                try:
                    fn.discardData()
                    for i, row in enumerate(table_data):
                        fn.setIndex("table", row[0], i, 0)
                        fn.setIndex("table", row[1], i, 1)
                    info(f"  func '{ftag}': {len(table_data)} table rows (source=table)")
                except Exception as e: warn(f"  func '{ftag}' table: {e}")
            else:
                info(f"  func '{ftag}' ({ftype})")
            
            # Two-layer disable logic
            should_disable = False
            reason = ""
            if not fd.get("active", True):
                should_disable = True
                reason = "recipe"
            elif ftag.startswith("builder_"):
                should_disable = True
                reason = "3D safety: builder_* references thermo internals"
            
            if should_disable:
                try:
                    fn.active(False)
                    func_disabled += 1
                    info(f"    → DISABLED ({reason})")
                except Exception as e:
                    warn(f"    → DISABLE FAILED ({reason}): {e}")
            
            func_created += 1
        except Exception as e: warn(f"  func {ftag}: {e}")
    info(f"  Functions: {func_created} created, {func_disabled} disabled")
    
    # --- Couplings (two-layer: skip auto-generated, recipe + 3D safety) ---
    cpl_ok, cpl_skipped, cpl_disabled = 0, 0, 0
    for cd in defs.get("couplings", []):
        ctag, ctype = cd.get("tag",""), cd.get("type","")
        if not ctag or not ctype: continue
        
        # Skip physics-auto-generated couplings
        opname = str(cd.get("properties", {}).get("opname", ""))
        if "root.comp1." in opname:
            cpl_skipped += 1
            continue
        
        try:
            cn = comp_node.cpl().create(ctag, ctype)
            for k, v in filter_properties(cd.get("properties", {})).items():
                safe_set(cn, k, flatten_value(v))
            
            # Two-layer disable logic
            should_disable = False
            reason = ""
            if not cd.get("active", True):
                should_disable = True
                reason = "recipe"
            elif ctag.startswith("builder_"):
                should_disable = True
                reason = "3D safety: builder_* coupling"
            
            if should_disable:
                try:
                    cn.active(False)
                    cpl_disabled += 1
                    info(f"  coupling '{ctag}' ({ctype}) → DISABLED ({reason})")
                except Exception as e:
                    warn(f"  coupling '{ctag}' ({ctype}) → DISABLE FAILED ({reason}): {e}")
            else:
                info(f"  coupling '{ctag}' ({ctype})")
            cpl_ok += 1
        except: pass
    info(f"  Couplings: {cpl_ok} created ({cpl_disabled} disabled), {cpl_skipped} physics-auto skipped")
    
    # Thermodynamics
    banner("Thermodynamics")
    for td in recipe.get("global_definitions", {}).get("thermodynamics", []):
        tag = td.get("tag", "")
        ttype = td.get("type", "")
        props = td.get("properties", {})
        children = td.get("_children", [])
        
        info(f"Creating '{tag}' ({ttype})...")
        try:
            thermo_feat = jm.thermodynamics().feature().create(tag, ttype)
            
            pd = props.get("persistence_data", "")
            if pd:
                if isinstance(pd, list): pd = "".join(str(s) for s in pd)
                pd = str(pd)
                if pd.startswith("<?xml") or pd.startswith("<"):
                    thermo_feat.set("persistence_data", pd)
                    info(f"  persistence_data: {len(pd)} chars")
            
            for k, v in props.items():
                if k == "persistence_data": continue
                safe_set(thermo_feat, k, flatten_value(v))
            
            if children:
                info(f"  Creating {len(children)} property features...")
                for child in children:
                    ctag = child.get("tag", "")
                    ctype = child.get("type", "")
                    try:
                        cn = thermo_feat.feature().create(ctag, ctype)
                        for k, v in child.get("properties", {}).items():
                            safe_set(cn, k, flatten_value(v))
                        info(f"    ✓ {ctag}: {child.get('label','')}")
                    except Exception as e:
                        warn(f"    ✗ {ctag}: {e}")
        except Exception as e:
            warn(f"  Failed: {e}")
    
    # Selection mapper (needed for materials AND physics)
    mapper = CylinderSelectionMapper(jm, "geom1",
        comp_data.get("boundary_coord_map", {}),
        comp_data.get("domain_coord_map", {}))

    # Materials (must be before physics)
    create_materials(jm, recipe, mapper)

    # Physics (recipe-driven active state + domain selections)
    banner("Physics (Cylinder Selection Remapping)")
    
    physics = comp_data.get("physics", {})
    remap_ok, remap_fail, skip_count = 0, 0, 0
    phys_disabled, feat_disabled = 0, 0
    
    RADIATION_PHYSICS = {"SurfaceToSurfaceRadiation", "RadiationInParticipatingMedia"}
    for ptag, pdata in physics.items():
        ptype = pdata.get("type", "")
        features = pdata.get("features", [])
        p_active = pdata.get("active", True)

        # Override: disable radiation physics for convergence testing
        if DISABLE_RADIATION and ptype in RADIATION_PHYSICS:
            info(f"SKIP '{ptag}' ({ptype}) — DISABLE_RADIATION=True")
            continue

        act_str = "" if p_active else " [will disable]"
        info(f"Creating '{ptag}' ({ptype}){act_str}...")
        try:
            phys = jm.physics().create(ptag, ptype, "geom1")
            
            # v10: Apply physics-level domain selection from recipe
            phys_sel = pdata.get("selection", {})
            if phys_sel and phys_sel.get("indices"):
                sel_indices_2d = phys_sel["indices"]
                sel_dim = phys_sel.get("dimension", 2)
                if sel_dim >= 2:
                    mapped_3d = mapper.map_domains(sel_indices_2d)
                    if mapped_3d:
                        try:
                            phys.selection().set(mapped_3d)
                            info(f"    Domain selection: 2D {sel_indices_2d} → 3D {mapped_3d}")
                        except: pass
            
            for fd in features:
                ft, ftype = fd.get("tag",""), fd.get("type","")
                fprops, findices = fd.get("properties",{}), fd.get("selection_indices",[])
                fedim = fd.get("entity_dimension", -1)
                f_active = fd.get("active", True)
                
                if ftype in SKIP_IN_3D:
                    skip_count += 1; continue
                
                feat_node = None
                is_new = False
                try: feat_node = phys.feature(ft)
                except:
                    try:
                        feat_node = phys.feature().create(ft, ftype)
                        is_new = True
                    except Exception as e:
                        warn(f"    ✗ {ft}: {e}"); continue
                
                if is_new: info(f"    + {ft} ({ftype})")
                
                for k, v in filter_properties(fprops).items():
                    safe_set(feat_node, k, flatten_value(v))
                
                if findices:
                    dim_hint = fedim if fedim > 0 else guess_dim_2d(ftype)
                    if mapper.apply_selection(feat_node, findices, dim_hint):
                        remap_ok += 1
                        info(f"      ✓ Selection mapped")
                    else:
                        remap_fail += 1
                
                # v10: Apply feature-level active state from recipe
                if not f_active:
                    try:
                        feat_node.active(False)
                        feat_disabled += 1
                    except: pass
            
            # v10: Apply physics interface-level active state
            if not p_active:
                try:
                    phys.active(False)
                    phys_disabled += 1
                    info(f"    → DISABLED (from recipe)")
                except: pass
                
        except Exception as e: warn(f"  {ptag}: {e}")
    
    info(f"\n  Summary: {skip_count} axial skipped, {remap_ok} sel ok, {remap_fail} sel failed")
    info(f"  Physics: {phys_disabled} interfaces disabled, {feat_disabled} features disabled")
    
    # Multiphysics (recipe-driven + dependency checking)
    # Build set of ACTIVE physics tags for dependency checking
    banner("Multiphysics")
    active_physics = {ptag for ptag, pdata in physics.items() 
                      if pdata.get("active", True)}
    info(f"  Active physics: {sorted(active_physics)}")
    
    # Known multiphysics dependencies (type → required physics tags)
    MP_DEPS = {
        "ReactingFlow": lambda tag: {"spf", tag.replace("rfd", "tds").replace("1","").replace("2","2") 
                                      if "2" in tag else "tds"},
        "NonIsothermalFlow": lambda tag: {"spf", "ht"},
        "HeatTransferWithSurfaceToSurfaceRadiation": lambda tag: {"ht", "rad"},
    }
    
    mp_list = comp_data.get("multiphysics", [])
    mp_disabled, mp_skipped = 0, 0
    if mp_list:
        for mp in mp_list:
            mptag = mp.get("tag", "")
            mptype = mp.get("type", "")
            mp_active = mp.get("active", True)
            if not mptag or not mptype: continue

            # Skip inactive multiphysics entirely — creating then disabling can still
            # cause variable conflicts (e.g. ReactingFlowDS expects tds which is disabled)
            if not mp_active:
                mp_skipped += 1
                info(f"  SKIP inactive {mptag} ({mptype}) — from recipe")
                continue

            # Skip radiation-dependent couplings when DISABLE_RADIATION=True
            RADIATION_MP_TYPES = {"HeatTransferWithSurfaceToSurfaceRadiation",
                                   "RadiationInParticipatingMedia"}
            if DISABLE_RADIATION and mptype in RADIATION_MP_TYPES:
                mp_skipped += 1
                info(f"  SKIP {mptag} ({mptype}) — DISABLE_RADIATION=True")
                continue

            # Check if required physics are active (by type, covering variant names)
            REACTING_FLOW_TYPES = {"ReactingFlow", "ReactingFlowDS", "ReactingFlowConcentrated"}
            if mptype in REACTING_FLOW_TYPES:
                # rfd1 needs spf+tds, rfd2 needs spf+tds2
                req = {"spf", "tds2" if "2" in mptag else "tds"}
                missing = req - active_physics
                if missing:
                    mp_skipped += 1
                    info(f"  ✗ SKIP {mptag} ({mptype}) — requires disabled physics: {missing}")
                    continue

            try:
                mpnode = jm.multiphysics().create(mptag, mptype, "geom1")
                info(f"  ✓ {mptag} ({mptype})")
            except Exception as e: warn(f"  {mptag}: {e}")
    else:
        # Fallback for old recipes
        ptags = set(physics.keys())
        for tag, ctype, req in [("nitf1","NonIsothermalFlow",{"spf","ht"}),
                                 ("rfd1","ReactingFlow",{"spf","tds"}),
                                 ("rfd2","ReactingFlow",{"spf","tds2"})]:
            if req.issubset(ptags) and req.issubset(active_physics):
                try: jm.multiphysics().create(tag, ctype, "geom1"); info(f"  ✓ {tag}")
                except Exception as e: warn(f"  {tag}: {e}")
            elif not req.issubset(active_physics):
                info(f"  ✗ SKIP {tag} — requires disabled physics: {req - active_physics}")
    info(f"  {mp_skipped} skipped (inactive or missing deps)")
    
    # Mesh
    banner("Mesh")
    mesh = jm.mesh().create("mesh1", "geom1")
    mesh.autoMeshSize(MESH_SIZE)
    try: mesh.run(); info("✓ Mesh built!")
    except Exception as e: warn(f"Mesh: {e}")
    
    # Studies (recipe-driven active state)
    banner("Studies")
    study_disabled = 0
    study_count = 0
    for stag, steps in recipe.get("studies", {}).items():
        if not steps: continue
        try:
            study = jm.study().create(stag)
            study_count += 1
            for sd in steps:
                try:
                    sd_tag = sd.get("tag", "")
                    sd_type = sd.get("type", "")
                    if not sd_tag or not sd_type:
                        warn(f"  {stag}: step missing tag/type: {list(sd.keys())}")
                        continue
                    step = study.feature().create(sd_tag, sd_type)
                    for k, v in filter_properties(sd.get("properties", {})).items():
                        safe_set(step, k, flatten_value(v))
                    # Apply active state from recipe
                    if not sd.get("active", True):
                        try:
                            step.active(False)
                            study_disabled += 1
                            info(f"  {stag}/{sd_tag} → DISABLED")
                        except:
                            info(f"  {stag}/{sd_tag}")
                    else:
                        info(f"  {stag}/{sd_tag}")
                except Exception as e:
                    warn(f"  {stag}/{sd.get('tag','?')}: {e}")
        except Exception as e:
            warn(f"  Study {stag}: {e}")
    info(f"  {study_count} studies, {study_disabled} steps disabled")
    
    # Save
    banner("Save")
    path = os.path.join(os.getcwd(), OUTPUT_FILE)
    try: model.save(path); info(f"✓ {path}")
    except Exception as e: warn(f"Save: {e}")
    
    banner("DONE — Open shelly_model_3D_v10.mph")
    info(f"Selections: {remap_ok} ok, {remap_fail} failed, {skip_count} axial skipped")
    info(f"Couplings: {cpl_ok} created ({cpl_disabled} disabled), {cpl_skipped} physics-auto skipped")
    info(f"Functions: {func_created} created, {func_disabled} disabled")
    info(f"Physics: {phys_disabled} interfaces disabled, {feat_disabled} features disabled")
    info(f"")
    info(f"All active/disabled states applied from recipe (memorizer v12).")
    info(f"")
    info(f"MANUAL STEPS REQUIRED:")
    info(f"  1. Right-click Thermodynamic System 1 (pp1) → Define System")
    info(f"  2. Right-click pp1 → Generate Material")
    info(f"  3. Set mole fractions for each gas composition (see log above)")


if __name__ == "__main__":
    main()