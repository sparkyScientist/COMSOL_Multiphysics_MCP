#!/usr/bin/env python
"""
memorize_workflows.py v11.0 — "The Universal Digital Twin"
============================================================
Builds on v10 with three critical additions:

1. INTERPOLATION TABLES: Captures actual data via getStringMatrix("table")
   so the converter can recreate interpolation functions with their data.

2. COORDINATE MAPS: Extracts boundary and domain coordinates from the mesh
   using getElem/getElemEntity/getVertex. This enables 2D→3D selection
   remapping after revolve operations.

3. THERMODYNAMICS CHILDREN: Captures the OnePhaseProperty children of
   BuiltinPropertyPackage (Density, Cp, Cp/Cv, k, μ) with full properties,
   so the converter can recreate them manually.

Run with ANY model loaded on the COMSOL server (port 2036).
"""

import mph
import json
import os
import traceback

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("  Warning: numpy not available. Coordinate maps will be skipped.")

print("=" * 68)
print("  COMSOL Master Memorizer v11.0 (Universal Digital Twin)")
print("=" * 68)

COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment

RECIPE_FILE = "comsol_recipes.json"
client = mph.Client(port=COMSOL_PORT)
model = client.models()[-1]
model_name = str(model.name())
jm = model.java

print(f"  Model: '{model_name}'")

# ── PHASE 0: FORCE BUILD ─────────────────────────────────────────────

print("\n  Force-building geometry...")
try:
    for comp_tag in [str(t) for t in list(jm.component().tags())]:
        comp = jm.component(comp_tag)
        for g_tag in [str(t) for t in list(comp.geom().tags())]:
            print(f"    Building geometry: {g_tag}")
            comp.geom(g_tag).runAll()
        for m_tag in [str(t) for t in list(comp.mesh().tags())]:
            print(f"    Building mesh: {m_tag}")
            try:
                comp.mesh(m_tag).run()
            except Exception as me:
                print(f"    Mesh build warning: {me}")
except Exception as e:
    print(f"    Warning: {e}")


# ── HELPERS ───────────────────────────────────────────────────────────

def safe_str(val):
    try: return str(val)
    except: return "CONVERSION_ERROR"


def get_full_props(node):
    """Exhaustive property extraction."""
    props = {}
    try:
        p_list = [str(p) for p in list(node.properties())]
        for p in p_list:
            try:
                val = node.getStringArray(p)
                props[p] = [safe_str(s) for s in list(val)]
            except:
                try: props[p] = safe_str(node.getString(p))
                except:
                    try: props[p] = safe_str(node.get(p))
                    except: continue
    except: pass
    return props


def get_selection_info(node):
    """Extract selection data handling non-editable selections."""
    result = {
        "selection_type": "unknown",
        "selection_indices": [],
        "bounding_box": {},
        "named_selection": "",
        "entity_dimension": -1,
    }
    try: sel = node.selection()
    except: return result
    
    try: result["selection_type"] = safe_str(sel.getType())
    except: pass
    try: result["named_selection"] = safe_str(sel.named())
    except: pass
    
    # Try entities at each dimension
    for try_dim in [2, 1, 3, 0]:
        try:
            ents = list(sel.entities(try_dim))
            if ents:
                result["selection_indices"] = [int(i) for i in ents]
                result["entity_dimension"] = try_dim
                break
        except: continue
    
    # Fallback to all()
    if not result["selection_indices"]:
        try: result["selection_indices"] = [int(i) for i in list(sel.all())]
        except: pass
    
    # Fallback to inputEntities()
    if not result["selection_indices"]:
        try:
            for try_dim in [2, 1, 3, 0]:
                ents = list(sel.inputEntities(try_dim))
                if ents:
                    result["selection_indices"] = [int(i) for i in ents]
                    result["entity_dimension"] = try_dim
                    break
        except: pass
    
    # Bounding box
    if result["selection_indices"]:
        try:
            result["bounding_box"] = {
                "min": [float(x) for x in list(sel.low())],
                "max": [float(x) for x in list(sel.high())]
            }
        except: pass
    
    return result


def get_node_info(node):
    """Full node info with properties and selection."""
    info = {
        "tag": safe_str(node.tag()) if hasattr(node, 'tag') else "N/A",
        "type": safe_str(node.getType()) if hasattr(node, 'getType') else "unknown",
        "label": safe_str(node.label()) if hasattr(node, 'label') else "N/A",
        "properties": get_full_props(node),
    }
    info.update(get_selection_info(node))
    return info


def scan_branch(branch):
    """Universal branch scanner."""
    items = []
    try:
        tags = [str(t) for t in list(branch.feature().tags())]
        for t in tags:
            try: items.append(get_node_info(branch.feature(t)))
            except Exception as e: items.append({"tag": t, "error": safe_str(e)})
        return items
    except: pass
    try:
        tags = [str(t) for t in list(branch.tags())]
        for t in tags:
            try: items.append(get_node_info(branch.get(t)))
            except:
                try: items.append(get_node_info(branch(t)))
                except Exception as e: items.append({"tag": t, "error": safe_str(e)})
        return items
    except: pass
    return items


def extract_variable_table(var_node):
    """Extract name→expression→description from variable group."""
    table = {}
    try:
        varnames = [safe_str(v) for v in list(var_node.varnames())]
        for vname in varnames:
            try: expr = safe_str(var_node.get(vname))
            except: expr = ""
            try: descr = safe_str(var_node.descr(vname))
            except: descr = ""
            table[vname] = {"expression": expr, "description": descr}
    except: pass
    return {"variables": table, "properties": get_full_props(var_node)}


def extract_function_info(func_node):
    """Extract function with interpolation table data."""
    info = get_node_info(func_node)
    func_type = info.get("type", "")
    
    # NEW v11: Capture interpolation table data via getStringMatrix
    if func_type == "Interpolation":
        try:
            matrix = func_node.getStringMatrix("table")
            rows = [[str(cell) for cell in list(row)] for row in list(matrix)]
            info["table_data"] = rows
            print(f"      Table: {len(rows)} rows x {len(rows[0])} cols")
        except Exception as e:
            print(f"      Table extraction failed: {e}")
    
    # Also try function_data for other types
    if func_type in ("Interpolation", "PiecewiseAnalytic", "Piecewise"):
        try:
            info["function_data"] = {}
            for prop in ["arg", "argunit", "fununit"]:
                try:
                    val = func_node.getStringArray(prop)
                    info["function_data"][prop] = [safe_str(s) for s in list(val)]
                except:
                    try: info["function_data"][prop] = safe_str(func_node.getString(prop))
                    except: pass
        except: pass
    
    return info


def extract_coupling_info(cpl_node):
    """Extract coupling with selection data."""
    info = get_node_info(cpl_node)
    info.update(get_selection_info(cpl_node))
    return info


# ── NEW v11: COORDINATE MAP EXTRACTION ────────────────────────────────

def extract_coordinate_maps(comp, comp_data):
    """
    Extract boundary and domain coordinate maps from mesh vertices.
    Uses getElem/getElemEntity/getVertex to find spatial coordinates
    for each geometric entity. Works for 2D and 3D models.
    """
    if not HAS_NUMPY:
        print("    Skipping coord maps (numpy not available)")
        return
    
    try:
        # Find the first mesh sequence
        mesh_tags = [str(t) for t in list(comp.mesh().tags())]
        if not mesh_tags:
            print("    No mesh found — skipping coord maps")
            return
        mesh = comp.mesh(mesh_tags[0])
        vtx = np.array(mesh.getVertex())
        n_dims = vtx.shape[0]
        print(f"    Mesh: {vtx.shape[1]} vertices, {n_dims}D")
    except Exception as e:
        print(f"    Mesh access failed: {e}")
        return
    
    # Determine which element types exist
    # 2D: edg (boundaries), tri/quad (domains)
    # 3D: tri (boundaries), tet/hex/prism (domains)
    
    # Boundary elements
    boundary_map = {}
    boundary_etypes = ['edg', 'tri']  # edg for 2D boundaries, tri for 3D boundaries
    for etype in boundary_etypes:
        try:
            elems = np.array(mesh.getElem(etype))
            ents = np.array(mesh.getElemEntity(etype))
            unique_ents = sorted(set(ents.tolist()))
            
            if not unique_ents:
                continue
            
            for eidx in unique_ents:
                mask = ents == eidx
                verts = np.unique(elems[:, mask])
                coords = vtx[:, verts]
                
                entry = {}
                if n_dims >= 2:
                    entry["r_min"] = round(float(coords[0].min()), 8)
                    entry["r_max"] = round(float(coords[0].max()), 8)
                    entry["z_min"] = round(float(coords[1].min()), 8)
                    entry["z_max"] = round(float(coords[1].max()), 8)
                    # Flags for 2D axisymmetric
                    entry["is_axial"] = entry["r_min"] == 0.0 and entry["r_max"] == 0.0
                    entry["is_horizontal"] = abs(entry["z_max"] - entry["z_min"]) < 1e-6
                    entry["is_vertical"] = abs(entry["r_max"] - entry["r_min"]) < 1e-6
                if n_dims >= 3:
                    entry["x_min"] = round(float(coords[0].min()), 8)
                    entry["x_max"] = round(float(coords[0].max()), 8)
                    entry["y_min"] = round(float(coords[1].min()), 8)
                    entry["y_max"] = round(float(coords[1].max()), 8)
                    entry["z_min"] = round(float(coords[2].min()), 8)
                    entry["z_max"] = round(float(coords[2].max()), 8)
                
                boundary_map[str(int(eidx))] = entry
            
            if boundary_map:
                print(f"    Boundary coord map ({etype}): {len(boundary_map)} entities")
                break  # Use first successful element type
        except:
            continue
    
    comp_data["boundary_coord_map"] = boundary_map
    
    # Domain elements
    domain_map = {}
    domain_etypes = ['tri', 'quad', 'tet', 'hex', 'prism']
    seen_domains = set()
    
    for etype in domain_etypes:
        try:
            elems = np.array(mesh.getElem(etype))
            ents = np.array(mesh.getElemEntity(etype))
            
            for didx in sorted(set(ents.tolist())):
                if didx in seen_domains:
                    continue
                seen_domains.add(didx)
                
                mask = ents == didx
                verts = np.unique(elems[:, mask])
                coords = vtx[:, verts]
                
                entry = {}
                if n_dims >= 2:
                    entry["r_min"] = round(float(coords[0].min()), 8)
                    entry["r_max"] = round(float(coords[0].max()), 8)
                    entry["z_min"] = round(float(coords[1].min()), 8)
                    entry["z_max"] = round(float(coords[1].max()), 8)
                if n_dims >= 3:
                    entry["x_min"] = round(float(coords[0].min()), 8)
                    entry["x_max"] = round(float(coords[0].max()), 8)
                    entry["y_min"] = round(float(coords[1].min()), 8)
                    entry["y_max"] = round(float(coords[1].max()), 8)
                    entry["z_min"] = round(float(coords[2].min()), 8)
                    entry["z_max"] = round(float(coords[2].max()), 8)
                
                domain_map[str(int(didx))] = entry
        except:
            continue
    
    comp_data["domain_coord_map"] = domain_map
    print(f"    Domain coord map: {len(domain_map)} entities")


# ── NEW v11: THERMODYNAMICS CHILDREN ──────────────────────────────────

def extract_thermodynamics(jm):
    """
    Extract thermodynamics with full children (OnePhaseProperty features).
    Uses jm.thermodynamics().feature() path for COMSOL 6.3 API.
    """
    thermo_list = []
    
    try:
        thermo = jm.thermodynamics()
        feat_tags = [str(t) for t in list(thermo.feature().tags())]
        
        for ftag in feat_tags:
            feat = thermo.feature(ftag)
            info = {
                "tag": ftag,
                "type": safe_str(feat.getType()),
                "label": safe_str(feat.label()),
                "properties": get_full_props(feat),
                "_children": [],
            }
            
            # Extract children (OnePhaseProperty features)
            try:
                child_tags = [str(t) for t in list(feat.feature().tags())]
                for ctag in child_tags:
                    child = feat.feature(ctag)
                    child_info = {
                        "tag": ctag,
                        "type": safe_str(child.getType()),
                        "label": safe_str(child.label()),
                        "properties": {},
                    }
                    # Get all child properties
                    try:
                        for p in [str(pr) for pr in list(child.properties())]:
                            try: child_info["properties"][p] = safe_str(child.getString(p))
                            except:
                                try: child_info["properties"][p] = [safe_str(s) for s in list(child.getStringArray(p))]
                                except: pass
                    except: pass
                    
                    info["_children"].append(child_info)
                
                print(f"    Thermo {ftag}: {len(child_tags)} property features")
            except Exception as e:
                print(f"    Thermo {ftag} children: {e}")
            
            thermo_list.append(info)
    except Exception as e:
        print(f"    Thermodynamics scan failed: {e}")
        # Fallback to scan_branch
        try:
            thermo_list = scan_branch(jm.thermodynamics())
        except: pass
    
    return thermo_list


# ═══════════════════════════════════════════════════════════════════════
# BUILD THE RECIPE
# ═══════════════════════════════════════════════════════════════════════

print("\n  Extracting global parameters...")
recipe = {
    "parameters": {},
    "global_definitions": {
        "variables": [],
        "functions": [],
        "materials": [],
        "thermodynamics": [],
    },
    "components": {},
    "studies": {},
    "results": {},
}

# Parameters
try:
    param_names = [str(p) for p in list(jm.param().varnames())]
    for pname in param_names:
        recipe["parameters"][pname] = {
            "expression": safe_str(jm.param().get(pname)),
            "description": safe_str(jm.param().descr(pname)),
        }
    print(f"    Parameters: {len(recipe['parameters'])}")
except Exception as e:
    print(f"    Parameters failed: {e}")

# Global definitions
print("  Extracting global definitions...")

try:
    gvar_tags = [str(t) for t in list(jm.variable().tags())]
    for vtag in gvar_tags:
        vnode = jm.variable(vtag)
        recipe["global_definitions"]["variables"].append({
            "tag": vtag,
            "label": safe_str(vnode.label()) if hasattr(vnode, 'label') else vtag,
            **extract_variable_table(vnode)
        })
    print(f"    Global variables: {len(gvar_tags)}")
except Exception as e:
    print(f"    Global variables failed: {e}")

try:
    gfunc_tags = [str(t) for t in list(jm.func().tags())]
    for ftag in gfunc_tags:
        recipe["global_definitions"]["functions"].append(
            extract_function_info(jm.func(ftag))
        )
    print(f"    Global functions: {len(gfunc_tags)}")
except Exception as e:
    print(f"    Global functions failed: {e}")

try:
    recipe["global_definitions"]["materials"] = scan_branch(jm.material())
    print(f"    Global materials: {len(recipe['global_definitions']['materials'])}")
except: pass

# NEW v11: Thermodynamics with children
print("  Extracting thermodynamics...")
recipe["global_definitions"]["thermodynamics"] = extract_thermodynamics(jm)

# ── COMPONENT SCAN ────────────────────────────────────────────────────

print("\n  Scanning components...")

for c_tag in [str(t) for t in list(jm.component().tags())]:
    comp = jm.component(c_tag)
    print(f"\n  Component: {c_tag}")
    
    comp_data = {
        "definitions": {
            "selections": [], "variables": [], "functions": [],
            "probes": [], "couplings": [],
        },
        "geometry": {},
        "materials": [],
        "physics": {},
        "multiphysics": [],
        "mesh": [],
        "boundary_coord_map": {},
        "domain_coord_map": {},
    }
    
    # Variables
    try:
        var_tags = [str(t) for t in list(comp.variable().tags())]
        for vtag in var_tags:
            vnode = comp.variable(vtag)
            comp_data["definitions"]["variables"].append({
                "tag": vtag,
                "label": safe_str(vnode.label()) if hasattr(vnode, 'label') else vtag,
                **extract_variable_table(vnode)
            })
        print(f"    Variables: {len(var_tags)}")
    except Exception as e:
        print(f"    Variables failed: {e}")
    
    # Functions (with table data for Interpolation)
    try:
        func_tags = [str(t) for t in list(comp.func().tags())]
        for ftag in func_tags:
            comp_data["definitions"]["functions"].append(
                extract_function_info(comp.func(ftag))
            )
        print(f"    Functions: {len(func_tags)}")
    except Exception as e:
        print(f"    Functions failed: {e}")
    
    # Couplings
    try:
        cpl_tags = [str(t) for t in list(comp.cpl().tags())]
        for ctag in cpl_tags:
            comp_data["definitions"]["couplings"].append(
                extract_coupling_info(comp.cpl(ctag))
            )
        print(f"    Couplings: {len(cpl_tags)}")
    except Exception as e:
        print(f"    Couplings failed: {e}")
    
    # Selections
    try:
        sel_tags = [str(t) for t in list(comp.selection().tags())]
        for stag in sel_tags:
            comp_data["definitions"]["selections"].append(
                get_node_info(comp.selection(stag))
            )
        print(f"    Selections: {len(sel_tags)}")
    except Exception as e:
        print(f"    Selections failed: {e}")
    
    # Probes
    try:
        probe_tags = [str(t) for t in list(comp.probe().tags())]
        for ptag in probe_tags:
            comp_data["definitions"]["probes"].append(
                get_node_info(comp.probe(ptag))
            )
        print(f"    Probes: {len(probe_tags)}")
    except Exception as e:
        print(f"    Probes failed: {e}")
    
    # Geometry
    try:
        geom_tags = [str(t) for t in list(comp.geom().tags())]
        for gtag in geom_tags:
            comp_data["geometry"][gtag] = scan_branch(comp.geom(gtag))
        print(f"    Geometry: {len(geom_tags)} sequences")
    except Exception as e:
        print(f"    Geometry failed: {e}")
    
    # Materials with property groups
    mat_list = []
    try:
        mat_tags = [str(t) for t in list(comp.material().tags())]
        for mtag in mat_tags:
            mat = comp.material(mtag)
            minfo = get_node_info(mat)
            minfo['property_groups'] = {}
            try:
                pg_tags = [str(t) for t in list(mat.propertyGroup().tags())]
                for pgt in pg_tags:
                    pg = mat.propertyGroup(pgt)
                    pg_data = {'label': safe_str(pg.label()), 'properties': {}}
                    for p in [str(pr) for pr in list(pg.properties())]:
                        try: pg_data['properties'][p] = safe_str(pg.getString(p))
                        except:
                            try: pg_data['properties'][p] = [safe_str(s) for s in list(pg.getStringArray(p))]
                            except: pass
                    minfo['property_groups'][pgt] = pg_data
            except: pass
            minfo['_mat_children'] = []
            try:
                feat_tags = [str(t) for t in list(mat.feature().tags())]
                for ft in feat_tags:
                    f = mat.feature(ft)
                    child = {'tag': ft, 'type': safe_str(f.getType()), 'label': safe_str(f.label()), 'property_groups': {}}
                    try:
                        cpg_tags = [str(t) for t in list(f.propertyGroup().tags())]
                        for cpgt in cpg_tags:
                            cpg = f.propertyGroup(cpgt)
                            cpg_data = {'label': safe_str(cpg.label()), 'properties': {}}
                            for p in [str(pr) for pr in list(cpg.properties())]:
                                try: cpg_data['properties'][p] = safe_str(cpg.getString(p))
                                except:
                                    try: cpg_data['properties'][p] = [safe_str(s) for s in list(cpg.getStringArray(p))]
                                    except: pass
                            child['property_groups'][cpgt] = cpg_data
                    except: pass
                    minfo['_mat_children'].append(child)
            except: pass
            mat_list.append(minfo)
    except: pass
    comp_data['materials'] = mat_list
    print(f'    Materials: {len(mat_list)}')
    
    # Physics
    try:
        phys_tags = [str(t) for t in list(comp.physics().tags())]
        for ptag in phys_tags:
            pnode = comp.physics(ptag)
            ptype = safe_str(pnode.getType())
            features = []
            try:
                feat_tags = [str(t) for t in list(pnode.feature().tags())]
                for ftag in feat_tags:
                    features.append(get_node_info(pnode.feature(ftag)))
            except Exception as e:
                print(f"      Physics {ptag} features: {e}")
            
            comp_data["physics"][ptag] = {
                "type": ptype,
                "label": safe_str(pnode.label()) if hasattr(pnode, 'label') else ptag,
                "features": features,
            }
            n_sel = sum(1 for f in features if f.get("selection_indices"))
            print(f"    Physics {ptag} ({ptype}): {len(features)} features, {n_sel} with selections")
    except Exception as e:
        print(f"    Physics failed: {e}")
    
    # Multiphysics
    try:
        comp_data["multiphysics"] = scan_branch(comp.multiphysics())
        print(f"    Multiphysics: {len(comp_data['multiphysics'])}")
    except: pass
    
    # Mesh
    try:
        comp_data["mesh"] = scan_branch(comp.mesh())
        print(f"    Mesh: {len(comp_data['mesh'])} sequences")
    except: pass
    
    # NEW v11: Coordinate maps from mesh
    print("    Extracting coordinate maps...")
    extract_coordinate_maps(comp, comp_data)
    
    recipe["components"][c_tag] = comp_data

# Studies
print("\n  Scanning studies...")
try:
    study_tags = [str(t) for t in list(jm.study().tags())]
    for stag in study_tags:
        recipe["studies"][stag] = scan_branch(jm.study(stag))
    print(f"    Studies: {len(study_tags)}")
except Exception as e:
    print(f"    Studies failed: {e}")

# Results
print("  Scanning results...")
try:
    res = jm.result()
    recipe["results"] = {
        "datasets": scan_branch(res.dataset()),
        "numerical": scan_branch(res.numerical()),
        "plots": scan_branch(res),
    }
    print(f"    Datasets: {len(recipe['results'].get('datasets', []))}")
except Exception as e:
    print(f"    Results failed: {e}")

# ── SAVE ──────────────────────────────────────────────────────────────

print(f"\n  Saving to {RECIPE_FILE}...")
knowledge_base = {}
if os.path.exists(RECIPE_FILE):
    with open(RECIPE_FILE, "r") as f:
        try: knowledge_base = json.load(f)
        except: pass

knowledge_base[model_name] = recipe
with open(RECIPE_FILE, "w") as f:
    json.dump(knowledge_base, f, indent=4)

# ── SUMMARY ───────────────────────────────────────────────────────────

print("\n" + "=" * 68)
print("  EXTRACTION COMPLETE")
print("=" * 68)
print(f"  Model: {model_name}")
print(f"  Parameters: {len(recipe['parameters'])}")
print(f"  Thermodynamics: {len(recipe['global_definitions']['thermodynamics'])}")
for td in recipe['global_definitions']['thermodynamics']:
    print(f"    {td['tag']}: {len(td.get('_children', []))} property features")

for c_tag, c_data in recipe["components"].items():
    defs = c_data["definitions"]
    print(f"\n  Component {c_tag}:")
    print(f"    Variables: {len(defs['variables'])}")
    print(f"    Functions: {len(defs['functions'])}")
    print(f"    Couplings: {len(defs['couplings'])}")
    print(f"    Boundary coord map: {len(c_data.get('boundary_coord_map', {}))}")
    print(f"    Domain coord map: {len(c_data.get('domain_coord_map', {}))}")
    
    for ptag, pdata in c_data["physics"].items():
        feats = pdata["features"]
        n_sel = sum(1 for f in feats if f.get("selection_indices"))
        print(f"    Physics {ptag}: {len(feats)} features, {n_sel} with selections")

print(f"\n  Saved to: {RECIPE_FILE}")