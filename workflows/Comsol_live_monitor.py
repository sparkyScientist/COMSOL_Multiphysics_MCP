"""
comsol_live_monitor.py — MCP Tools for Live COMSOL Session Monitoring
=====================================================================
Connects to the running mphserver on port 2036 and provides real-time
inspection of the model state: solver status, errors, warnings, physics
configuration, material assignments, and mesh quality.

These tools let Claude act as a live co-pilot during COMSOL sessions.

Usage as MCP tools (register in src/server.py) or standalone diagnostic:
    python comsol_live_monitor.py          # run all diagnostics
    python comsol_live_monitor.py status    # quick status check
    python comsol_live_monitor.py errors    # solver errors only
"""

import mph
import json
import os
import sys
import traceback
from datetime import datetime

COMSOL_PORT = int(os.getenv("COMSOL_PORT", "2036"))  # configured via config.py / environment


# ═══════════════════════════════════════════════════════════════════════
# CONNECTION
# ═══════════════════════════════════════════════════════════════════════

_client = None
_model = None

def get_connection():
    """Get or create connection to mphserver. Returns (client, model_java)."""
    global _client, _model
    try:
        if _client is None:
            _client = mph.Client(port=COMSOL_PORT)
        
        # Get the first (or most recently active) model
        names = _client.names()
        if not names:
            return _client, None
        
        model = _client.models()[-1]  # most recent model
        _model = model
        return _client, model
    except Exception as e:
        return None, None


def get_java_model():
    """Get the Java model handle for direct API access."""
    client, model = get_connection()
    if model is None:
        return None, None, "No model loaded on mphserver"
    return client, model, None


# ═══════════════════════════════════════════════════════════════════════
# TOOL 1: MODEL STATUS
# ═══════════════════════════════════════════════════════════════════════

def tool_model_status():
    """
    MCP Tool: Get overview of the current model state.
    Returns: model name, components, physics, materials, studies, mesh status.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    result = {
        "timestamp": datetime.now().isoformat(),
        "model_tag": str(jm.tag()),
        "components": [],
        "physics": [],
        "materials": [],
        "studies": [],
        "mesh_status": None,
    }
    
    # Components
    try:
        for ctag in list(jm.component().tags()):
            result["components"].append(str(ctag))
    except: pass
    
    # Physics
    try:
        for ptag in list(jm.physics().tags()):
            try:
                phys = jm.physics(str(ptag))
                ptype = str(phys.getType())
                label = str(phys.label())
                n_feat = int(phys.feature().size())
                result["physics"].append({
                    "tag": str(ptag), "type": ptype,
                    "label": label, "features": n_feat
                })
            except: pass
    except: pass
    
    # Materials
    try:
        comp_node = jm.component("comp1")
        for mtag in list(comp_node.material().tags()):
            try:
                mat = comp_node.material(str(mtag))
                result["materials"].append({
                    "tag": str(mtag),
                    "label": str(mat.label()),
                    "type": str(mat.getType()),
                })
            except: pass
    except: pass
    
    # Studies
    try:
        for stag in list(jm.study().tags()):
            try:
                study = jm.study(str(stag))
                steps = []
                for ftag in list(study.feature().tags()):
                    feat = study.feature(str(ftag))
                    steps.append({
                        "tag": str(ftag),
                        "type": str(feat.getType()),
                        "active": bool(feat.isActive()),
                    })
                result["studies"].append({
                    "tag": str(stag),
                    "label": str(study.label()),
                    "steps": steps,
                })
            except: pass
    except: pass
    
    # Mesh status
    try:
        mesh = jm.mesh("mesh1")
        result["mesh_status"] = {
            "built": True,
            "num_elements": int(mesh.getNumElem()),
        }
    except:
        result["mesh_status"] = {"built": False}
    
    return result


# ═══════════════════════════════════════════════════════════════════════
# TOOL 2: SOLVER ERRORS & WARNINGS
# ═══════════════════════════════════════════════════════════════════════

def tool_solver_errors():
    """
    MCP Tool: Get solver errors and warnings from the most recent run.
    Checks study solutions for error messages.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    result = {
        "timestamp": datetime.now().isoformat(),
        "errors": [],
        "warnings": [],
        "solutions": [],
    }
    
    # Check each study for solution info
    try:
        for stag in list(jm.study().tags()):
            study = jm.study(str(stag))
            
            # Check if study has run (has solution)
            try:
                sol_tag = str(study.getSolver())
                if sol_tag:
                    result["solutions"].append({
                        "study": str(stag),
                        "solver": sol_tag,
                    })
            except: pass
    except: pass
    
    # Check solution objects for errors
    try:
        for stag in list(jm.sol().tags()):
            try:
                sol = jm.sol(str(stag))
                # Try to get solver log/info
                try:
                    info_str = str(sol.feature().tags())
                    result["solutions"].append({
                        "sol_tag": str(stag),
                        "features": info_str,
                    })
                except: pass
            except: pass
    except: pass
    
    # Check model warnings
    try:
        # COMSOL stores warnings in the model's message log
        msg_list = jm.modelMessages()
        if msg_list:
            for i in range(int(msg_list.size())):
                try:
                    msg = msg_list.get(i)
                    msg_type = str(msg.getType())
                    msg_text = str(msg.getMessage())
                    if "error" in msg_type.lower():
                        result["errors"].append(msg_text)
                    elif "warning" in msg_type.lower():
                        result["warnings"].append(msg_text)
                except: pass
    except: pass
    
    return result


# ═══════════════════════════════════════════════════════════════════════
# TOOL 3: PHYSICS INSPECTION
# ═══════════════════════════════════════════════════════════════════════

def tool_inspect_physics(physics_tag=None):
    """
    MCP Tool: Inspect physics interface details.
    If physics_tag given, returns features + selections for that interface.
    If None, returns summary of all interfaces.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    if physics_tag:
        # Detailed inspection of one physics interface
        try:
            phys = jm.physics(physics_tag)
            features = []
            for ftag in list(phys.feature().tags()):
                feat = phys.feature(str(ftag))
                fdata = {
                    "tag": str(ftag),
                    "type": str(feat.getType()),
                    "label": str(feat.label()),
                    "active": bool(feat.isActive()),
                }
                # Try to get selection
                try:
                    sel = feat.selection()
                    dim = int(sel.dimension())
                    try:
                        ents = [int(e) for e in list(sel.entities(dim))]
                        fdata["selection"] = {"dim": dim, "entities": ents}
                    except:
                        fdata["selection"] = {"dim": dim, "entities": "all"}
                except:
                    fdata["selection"] = None
                features.append(fdata)
            
            # Top-level selection
            top_sel = {}
            try:
                sel = phys.selection()
                dim = int(sel.dimension())
                ents = [int(e) for e in list(sel.entities(dim))]
                top_sel = {"dim": dim, "entities": ents}
            except:
                top_sel = {"dim": "?", "entities": "all/default"}
            
            return {
                "tag": physics_tag,
                "type": str(phys.getType()),
                "label": str(phys.label()),
                "top_level_selection": top_sel,
                "features": features,
            }
        except Exception as e:
            return {"error": f"Cannot inspect {physics_tag}: {e}"}
    else:
        # Summary of all
        return tool_model_status()["physics"]


# ═══════════════════════════════════════════════════════════════════════
# TOOL 4: MATERIAL INSPECTION
# ═══════════════════════════════════════════════════════════════════════

def tool_inspect_materials():
    """
    MCP Tool: Inspect all materials — types, selections, property groups.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    comp = jm.component("comp1")
    materials = []
    
    for mtag in list(comp.material().tags()):
        mat = comp.material(str(mtag))
        mdata = {
            "tag": str(mtag),
            "label": str(mat.label()),
            "type": str(mat.getType()),
            "property_groups": [],
        }
        
        # Selection
        try:
            sel = mat.selection()
            dim = int(sel.dimension())
            ents = [int(e) for e in list(sel.entities(dim))]
            mdata["selection"] = {"dim": dim, "entities": ents}
        except:
            mdata["selection"] = None
        
        # Property groups
        try:
            for pgtag in list(mat.propertyGroup().tags()):
                pg = mat.propertyGroup(str(pgtag))
                mdata["property_groups"].append(str(pgtag))
        except: pass
        
        materials.append(mdata)
    
    return materials


# ═══════════════════════════════════════════════════════════════════════
# TOOL 5: DEFINITIONS INSPECTION
# ═══════════════════════════════════════════════════════════════════════

def tool_inspect_definitions():
    """
    MCP Tool: Inspect definitions — variables, functions, couplings with
    their active/disabled status.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    comp = jm.component("comp1")
    result = {"variables": [], "functions": [], "couplings": []}
    
    # Variables
    try:
        for vtag in list(comp.variable().tags()):
            var = comp.variable(str(vtag))
            result["variables"].append({
                "tag": str(vtag),
                "active": bool(var.isActive()),
            })
    except: pass
    
    # Functions
    try:
        for ftag in list(comp.func().tags()):
            fn = comp.func(str(ftag))
            result["functions"].append({
                "tag": str(ftag),
                "type": str(fn.getType()),
                "active": bool(fn.isActive()),
                "label": str(fn.label()),
            })
    except: pass
    
    # Couplings
    try:
        for ctag in list(comp.cpl().tags()):
            cn = comp.cpl(str(ctag))
            result["couplings"].append({
                "tag": str(ctag),
                "type": str(cn.getType()),
                "active": bool(cn.isActive()),
            })
    except: pass
    
    return result


# ═══════════════════════════════════════════════════════════════════════
# TOOL 6: GET/SET PROPERTY
# ═══════════════════════════════════════════════════════════════════════

def tool_get_property(path, property_name):
    """
    MCP Tool: Get a property value from any model node.
    
    path: dot-separated path like "physics.spf.feature.inl1" or "component.comp1.material.mat3"
    property_name: the property to read, e.g. "U0" or "density"
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    try:
        # Navigate the path
        node = _resolve_path(jm, path)
        if node is None:
            return {"error": f"Cannot resolve path: {path}"}
        
        # Get the property
        val = node.getString(property_name)
        return {"path": path, "property": property_name, "value": str(val)}
    except Exception as e:
        return {"error": f"Cannot get {property_name} from {path}: {e}"}


def tool_set_property(path, property_name, value):
    """
    MCP Tool: Set a property value on any model node.
    
    path: dot-separated path like "physics.spf.feature.inl1"
    property_name: the property to set
    value: the value to set (string)
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    try:
        node = _resolve_path(jm, path)
        if node is None:
            return {"error": f"Cannot resolve path: {path}"}
        
        node.set(property_name, str(value))
        return {"status": "ok", "path": path, "property": property_name, "value": str(value)}
    except Exception as e:
        return {"error": f"Cannot set {property_name} on {path}: {e}"}


def _resolve_path(jm, path):
    """Resolve a dot-separated path to a COMSOL Java node."""
    parts = path.split(".")
    node = jm
    
    i = 0
    while i < len(parts):
        part = parts[i]
        
        # Known navigators
        if part == "physics":
            i += 1; node = jm.physics(parts[i])
        elif part == "component":
            i += 1; node = jm.component(parts[i])
        elif part == "material":
            i += 1; node = node.material(parts[i])
        elif part == "feature":
            i += 1; node = node.feature(parts[i])
        elif part == "study":
            i += 1; node = jm.study(parts[i])
        elif part == "mesh":
            i += 1; node = jm.mesh(parts[i])
        elif part == "param":
            node = jm.param()
        elif part == "propertyGroup":
            i += 1; node = node.propertyGroup(parts[i])
        elif part == "selection":
            node = node.selection()
        elif part == "func":
            i += 1; node = node.func(parts[i])
        elif part == "cpl":
            i += 1; node = node.cpl(parts[i])
        elif part == "variable":
            i += 1; node = node.variable(parts[i])
        elif part == "sol":
            i += 1; node = jm.sol(parts[i])
        elif part == "multiphysics":
            i += 1; node = jm.multiphysics(parts[i])
        else:
            # Try generic attribute access
            try: node = getattr(node, part)()
            except: return None
        
        i += 1
    
    return node


# ═══════════════════════════════════════════════════════════════════════
# TOOL 7: ENABLE/DISABLE FEATURE
# ═══════════════════════════════════════════════════════════════════════

def tool_toggle_feature(path, active=True):
    """
    MCP Tool: Enable or disable a model feature.
    
    path: dot-separated path to the feature
    active: True to enable, False to disable
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    try:
        node = _resolve_path(jm, path)
        if node is None:
            return {"error": f"Cannot resolve path: {path}"}
        
        node.active(active)
        return {"status": "ok", "path": path, "active": active}
    except Exception as e:
        return {"error": f"Cannot toggle {path}: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# TOOL 8: RUN STUDY
# ═══════════════════════════════════════════════════════════════════════

def tool_run_study(study_tag):
    """
    MCP Tool: Run a study. Returns success/failure with error details.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    try:
        jm.study(study_tag).run()
        return {"status": "ok", "study": study_tag}
    except Exception as e:
        return {"status": "error", "study": study_tag, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# TOOL 9: SAVE MODEL
# ═══════════════════════════════════════════════════════════════════════

def tool_save_model(filepath=None):
    """
    MCP Tool: Save the current model.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    try:
        if filepath:
            model.save(filepath)
        else:
            model.java.save()
        return {"status": "ok", "path": filepath or "(current path)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# TOOL 10: GEOMETRY INFO
# ═══════════════════════════════════════════════════════════════════════

def tool_geometry_info():
    """
    MCP Tool: Get geometry information — domains, boundaries, edges, points.
    """
    client, model, err = get_java_model()
    if err:
        return {"error": err}
    
    jm = model.java
    
    try:
        geom = jm.geom("geom1")
        return {
            "sdim": int(geom.getSDim()),
            "domains": int(geom.getNDomains()),
            "boundaries": int(geom.getNBoundaries()),
            "edges": int(geom.getNEdges()),
            "points": int(geom.getNPoints()),
            "features": [str(t) for t in list(geom.feature().tags())],
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# MCP SERVER REGISTRATION SNIPPET
# ═══════════════════════════════════════════════════════════════════════

MCP_TOOL_REGISTRY = """
# See comsol_live_monitor.py for registration snippet.
# 10 tools: status, errors, inspect_physics, inspect_materials,
# inspect_definitions, get_property, set_property, toggle_feature,
# run_study, save_model, geometry_info + watch mode.
"""


# ═══════════════════════════════════════════════════════════════════════
# DEEP STATE SNAPSHOT (for watch mode diffing)
# ═══════════════════════════════════════════════════════════════════════

def take_deep_snapshot():
    """
    Capture a comprehensive snapshot of the entire model state.
    This goes deeper than tool_model_status — it captures:
    - Every physics feature with selections and active status
    - Every material with property group contents
    - Every definition (var/func/coupling) with active status
    - Every study step with solver config
    - Geometry domain/boundary counts
    - Mesh element count
    - All parameter values
    
    Returns a flat, diffable dict.
    """
    client, model, err = get_java_model()
    if err:
        return {"_error": err}
    
    jm = model.java
    snap = {
        "_timestamp": datetime.now().isoformat(),
        "_model_tag": str(jm.tag()),
    }
    
    # Parameters
    try:
        param_names = list(jm.param().varnames())
        for pname in param_names:
            pname = str(pname)
            try:
                expr = str(jm.param().get(pname))
                snap[f"param.{pname}"] = expr
            except: pass
    except: pass
    
    # Geometry
    try:
        geom = jm.geom("geom1")
        snap["geom.sdim"] = int(geom.getSDim())
        snap["geom.domains"] = int(geom.getNDomains())
        snap["geom.boundaries"] = int(geom.getNBoundaries())
        snap["geom.edges"] = int(geom.getNEdges())
        feat_tags = [str(t) for t in list(geom.feature().tags())]
        snap["geom.features"] = feat_tags
    except: pass
    
    # Definitions — variables
    try:
        comp = jm.component("comp1")
        for vtag in list(comp.variable().tags()):
            vtag = str(vtag)
            var = comp.variable(vtag)
            snap[f"def.var.{vtag}.active"] = bool(var.isActive())
    except: pass
    
    # Definitions — functions
    try:
        comp = jm.component("comp1")
        for ftag in list(comp.func().tags()):
            ftag_s = str(ftag)
            fn = comp.func(ftag_s)
            snap[f"def.func.{ftag_s}.type"] = str(fn.getType())
            snap[f"def.func.{ftag_s}.active"] = bool(fn.isActive())
            snap[f"def.func.{ftag_s}.label"] = str(fn.label())
    except: pass
    
    # Definitions — couplings
    try:
        comp = jm.component("comp1")
        for ctag in list(comp.cpl().tags()):
            ctag_s = str(ctag)
            cn = comp.cpl(ctag_s)
            snap[f"def.cpl.{ctag_s}.type"] = str(cn.getType())
            snap[f"def.cpl.{ctag_s}.active"] = bool(cn.isActive())
    except: pass
    
    # Physics — deep: every interface + every feature + selections
    try:
        for ptag in list(jm.physics().tags()):
            ptag_s = str(ptag)
            phys = jm.physics(ptag_s)
            snap[f"physics.{ptag_s}.type"] = str(phys.getType())
            snap[f"physics.{ptag_s}.label"] = str(phys.label())
            snap[f"physics.{ptag_s}.active"] = bool(phys.isActive())
            
            # Top-level selection (domain assignment)
            try:
                sel = phys.selection()
                dim = int(sel.dimension())
                ents = sorted([int(e) for e in list(sel.entities(dim))])
                snap[f"physics.{ptag_s}.selection"] = ents
            except:
                snap[f"physics.{ptag_s}.selection"] = "all"
            
            # Features
            for ftag in list(phys.feature().tags()):
                ftag_s = str(ftag)
                feat = phys.feature(ftag_s)
                prefix = f"physics.{ptag_s}.feat.{ftag_s}"
                snap[f"{prefix}.type"] = str(feat.getType())
                snap[f"{prefix}.active"] = bool(feat.isActive())
                
                # Feature selection
                try:
                    fsel = feat.selection()
                    fdim = int(fsel.dimension())
                    fents = sorted([int(e) for e in list(fsel.entities(fdim))])
                    snap[f"{prefix}.selection"] = fents
                except:
                    snap[f"{prefix}.selection"] = "inherited"
    except: pass
    
    # Materials
    try:
        comp = jm.component("comp1")
        for mtag in list(comp.material().tags()):
            mtag_s = str(mtag)
            mat = comp.material(mtag_s)
            snap[f"mat.{mtag_s}.label"] = str(mat.label())
            snap[f"mat.{mtag_s}.type"] = str(mat.getType())
            snap[f"mat.{mtag_s}.active"] = bool(mat.isActive())
            
            # Selection
            try:
                msel = mat.selection()
                mdim = int(msel.dimension())
                ments = sorted([int(e) for e in list(msel.entities(mdim))])
                snap[f"mat.{mtag_s}.selection"] = ments
            except:
                snap[f"mat.{mtag_s}.selection"] = "none"
            
            # Property groups
            try:
                for pgtag in list(mat.propertyGroup().tags()):
                    snap[f"mat.{mtag_s}.pg.{str(pgtag)}"] = True
            except: pass
    except: pass
    
    # Multiphysics
    try:
        for mptag in list(jm.multiphysics().tags()):
            mptag_s = str(mptag)
            mp = jm.multiphysics(mptag_s)
            snap[f"multiphysics.{mptag_s}.type"] = str(mp.getType())
            snap[f"multiphysics.{mptag_s}.active"] = bool(mp.isActive())
    except: pass
    
    # Studies
    try:
        for stag in list(jm.study().tags()):
            stag_s = str(stag)
            study = jm.study(stag_s)
            snap[f"study.{stag_s}.label"] = str(study.label())
            
            for ftag in list(study.feature().tags()):
                ftag_s = str(ftag)
                feat = study.feature(ftag_s)
                prefix = f"study.{stag_s}.step.{ftag_s}"
                snap[f"{prefix}.type"] = str(feat.getType())
                snap[f"{prefix}.active"] = bool(feat.isActive())
    except: pass
    
    # Mesh
    try:
        mesh = jm.mesh("mesh1")
        snap["mesh.elements"] = int(mesh.getNumElem())
    except:
        snap["mesh.elements"] = 0
    
    # Solutions (solver state)
    try:
        sol_tags = [str(t) for t in list(jm.sol().tags())]
        snap["solutions"] = sol_tags
    except:
        snap["solutions"] = []
    
    return snap


def diff_snapshots(old, new):
    """
    Compare two snapshots and return categorized changes.
    Returns dict with: added, removed, changed keys.
    """
    all_keys = set(list(old.keys()) + list(new.keys()))
    # Skip internal keys
    all_keys = {k for k in all_keys if not k.startswith("_")}
    
    added = {}
    removed = {}
    changed = {}
    
    for k in sorted(all_keys):
        in_old = k in old
        in_new = k in new
        
        if in_new and not in_old:
            added[k] = new[k]
        elif in_old and not in_new:
            removed[k] = old[k]
        elif in_old and in_new and old[k] != new[k]:
            changed[k] = {"from": old[k], "to": new[k]}
    
    return {"added": added, "removed": removed, "changed": changed}


def format_diff(diff, elapsed_sec):
    """Pretty-print a diff for terminal output."""
    added = diff["added"]
    removed = diff["removed"]
    changed = diff["changed"]
    
    total = len(added) + len(removed) + len(changed)
    if total == 0:
        return None  # No changes
    
    lines = []
    lines.append(f"\n{'─'*60}")
    lines.append(f"  CHANGES DETECTED  ({total} modifications, {elapsed_sec:.0f}s since last)")
    lines.append(f"{'─'*60}")
    
    if added:
        lines.append(f"\n  ✚ ADDED ({len(added)}):")
        for k, v in added.items():
            lines.append(f"    + {k} = {_fmt_val(v)}")
    
    if removed:
        lines.append(f"\n  ✖ REMOVED ({len(removed)}):")
        for k, v in removed.items():
            lines.append(f"    - {k} (was {_fmt_val(v)})")
    
    if changed:
        lines.append(f"\n  ✎ CHANGED ({len(changed)}):")
        for k, v in changed.items():
            lines.append(f"    ~ {k}: {_fmt_val(v['from'])} → {_fmt_val(v['to'])}")
    
    return "\n".join(lines)


def _fmt_val(v):
    """Format a value for display, truncating long lists."""
    if isinstance(v, list) and len(v) > 8:
        return f"[{v[0]}, {v[1]}, ... {v[-1]}] ({len(v)} items)"
    return str(v)


# ═══════════════════════════════════════════════════════════════════════
# RECONNECT NOISE FILTER
# ═══════════════════════════════════════════════════════════════════════

def is_reconnect_noise(diff):
    """
    Detect if a diff is just a reconnect artifact (model briefly disappeared).
    
    Pattern: large number of items ALL removed or ALL added, with no changed.
    If >20 items removed and 0 added and 0 changed = disconnect.
    If >20 items added and 0 removed and 0 changed = reconnect.
    Also: if added and removed sets are >80% overlapping keys = bounce.
    """
    added = diff["added"]
    removed = diff["removed"]
    changed = diff["changed"]
    
    # Pure disconnect (everything vanishes)
    if len(removed) > 20 and len(added) == 0 and len(changed) == 0:
        return True
    
    # Pure reconnect (everything reappears)  
    if len(added) > 20 and len(removed) == 0 and len(changed) == 0:
        return True
    
    # Bounce: same keys removed then added back (or vice versa)
    if len(added) > 20 and len(removed) > 20:
        added_keys = set(added.keys())
        removed_keys = set(removed.keys())
        overlap = added_keys & removed_keys
        total = added_keys | removed_keys
        if total and len(overlap) / len(total) > 0.8:
            return True
    
    return False


def filter_builder_noise(diff):
    """
    Filter out builder_* coupling churn from diffs.
    COMSOL regenerates these internally — they appear/disappear 
    as side effects of Define System / Generate Material.
    """
    for category in ("added", "removed", "changed"):
        items = diff[category]
        diff[category] = {
            k: v for k, v in items.items()
            if "builder_" not in k
        }
    return diff


# ═══════════════════════════════════════════════════════════════════════
# PLAYBOOK: Distill session diffs into actionable steps
# ═══════════════════════════════════════════════════════════════════════

def classify_action(key, value, action_type):
    """
    Classify a single diff entry into a human-readable action category.
    Returns (category, description) tuple.
    """
    if action_type == "changed":
        old, new = value["from"], value["to"]
        
        # Active/disable toggle
        if key.endswith(".active"):
            node = key.rsplit(".active", 1)[0]
            if new == True:
                return ("enable", f"Enable {node}")
            else:
                return ("disable", f"Disable {node}")
        
        # Selection change
        if key.endswith(".selection"):
            node = key.rsplit(".selection", 1)[0]
            return ("selection", f"Change selection on {node}: {old} → {new}")
        
        # Parameter change
        if key.startswith("param."):
            pname = key.split(".", 1)[1]
            return ("parameter", f"Set parameter {pname} = {new}")
        
        # Mesh change
        if key.startswith("mesh."):
            return ("mesh", f"Mesh changed: {key} = {new}")
        
        return ("modify", f"Modify {key}: {old} → {new}")
    
    elif action_type == "added":
        # New material
        if key.startswith("mat.") and key.endswith(".label"):
            mtag = key.split(".")[1]
            return ("add_material", f"Add material {mtag}: {value}")
        
        # New physics
        if key.startswith("physics.") and key.endswith(".type"):
            ptag = key.split(".")[1]
            return ("add_physics", f"Add physics {ptag}: {value}")
        
        # New study step
        if key.startswith("study.") and key.endswith(".type"):
            parts = key.split(".")
            return ("add_study", f"Add study step {'.'.join(parts[1:3])}: {value}")
        
        return ("add", f"Add {key} = {value}")
    
    elif action_type == "removed":
        if key.startswith("mat.") and key.endswith(".label"):
            mtag = key.split(".")[1]
            return ("remove_material", f"Remove material {mtag} ({value})")
        
        if key.startswith("physics.") and key.endswith(".type"):
            ptag = key.split(".")[1]
            return ("remove_physics", f"Remove physics {ptag} ({value})")
        
        return ("remove", f"Remove {key}")
    
    return ("unknown", f"{action_type}: {key}")


def generate_playbook(change_log):
    """
    Distill a raw change log into a clean, ordered playbook of user actions.
    Deduplicates, groups by category, and filters noise.
    """
    actions = []
    step_num = 0
    
    for entry in change_log:
        step_actions = []
        
        # Process changed items
        for k, v in entry.get("changed", {}).items():
            cat, desc = classify_action(k, v, "changed")
            step_actions.append((cat, desc, k))
        
        # Process added items (only label/type keys to avoid noise)
        for k, v in entry.get("added", {}).items():
            if k.endswith((".label", ".type", ".active")) or k.startswith("param."):
                cat, desc = classify_action(k, v, "added")
                step_actions.append((cat, desc, k))
        
        # Process removed items (only label/type keys)
        for k, v in entry.get("removed", {}).items():
            if k.endswith((".label", ".type")) or k.startswith("param."):
                cat, desc = classify_action(k, v, "removed")
                step_actions.append((cat, desc, k))
        
        if not step_actions:
            continue
        
        # Group by category within this step
        step_num += 1
        by_cat = {}
        for cat, desc, key in step_actions:
            by_cat.setdefault(cat, []).append(desc)
        
        timestamp = entry.get("timestamp", "")
        actions.append({
            "step": step_num,
            "timestamp": timestamp,
            "actions": by_cat,
        })
    
    return actions


def format_playbook(playbook):
    """Format playbook as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  COMSOL SESSION PLAYBOOK")
    lines.append("  (Noise-filtered, actionable steps)")
    lines.append("=" * 60)
    
    for step in playbook:
        ts = step["timestamp"]
        if ts:
            ts = ts.split("T")[1].split(".")[0] if "T" in ts else ts
        lines.append(f"\n  Step {step['step']} [{ts}]:")
        
        for cat, descs in step["actions"].items():
            # Deduplicate
            seen = set()
            for d in descs:
                if d not in seen:
                    seen.add(d)
                    lines.append(f"    [{cat}] {d}")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE: Persistent lessons learned for MCP
# ═══════════════════════════════════════════════════════════════════════

KNOWLEDGE_BASE_FILE = "comsol_knowledge_base.json"

def load_knowledge_base():
    """Load the persistent knowledge base from disk."""
    try:
        with open(KNOWLEDGE_BASE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "version": 1,
            "created": datetime.now().isoformat(),
            "lessons": [],
            "converter_rules": [],
            "manual_steps": [],
            "session_count": 0,
        }


def save_knowledge_base(kb):
    """Save the knowledge base to disk."""
    kb["last_updated"] = datetime.now().isoformat()
    with open(KNOWLEDGE_BASE_FILE, "w") as f:
        json.dump(kb, f, indent=2, default=str)


def learn_from_session(change_log, playbook):
    """
    Analyze a session and extract lessons for the knowledge base.
    
    Patterns we detect:
    - User disabled something the converter created → lesson: don't create it / create disabled
    - User added something missing → lesson: converter should create it
    - User changed a selection → lesson: converter has wrong selection mapping
    - User changed solver settings → lesson: record preferred solver config
    """
    kb = load_knowledge_base()
    kb["session_count"] = kb.get("session_count", 0) + 1
    
    new_lessons = []
    
    # Analyze all changes across the session
    all_disables = []
    all_enables = []
    all_adds = {}
    all_removes = {}
    all_selection_changes = {}
    
    for entry in change_log:
        for k, v in entry.get("changed", {}).items():
            if k.endswith(".active"):
                node = k.rsplit(".active", 1)[0]
                if v.get("to") == False:
                    all_disables.append(node)
                elif v.get("to") == True:
                    all_enables.append(node)
            elif k.endswith(".selection"):
                node = k.rsplit(".selection", 1)[0]
                all_selection_changes[node] = {
                    "from": v.get("from"),
                    "to": v.get("to"),
                }
        
        for k, v in entry.get("added", {}).items():
            if k.endswith(".label"):
                all_adds[k.rsplit(".label", 1)[0]] = v
        
        for k, v in entry.get("removed", {}).items():
            if k.endswith(".label"):
                all_removes[k.rsplit(".label", 1)[0]] = v
    
    # Generate lessons from patterns
    
    # Pattern: User disabled physics interfaces
    disabled_physics = [n for n in all_disables if n.startswith("physics.") and n.count(".") == 1]
    if disabled_physics:
        new_lessons.append({
            "type": "disable_physics",
            "description": f"User disabled physics interfaces: {disabled_physics}",
            "detail": "These may not be needed for the initial solve. Consider creating them disabled or in a later study step.",
            "items": disabled_physics,
        })
    
    # Pattern: User disabled multiphysics couplings
    disabled_mp = [n for n in all_disables if n.startswith("multiphysics.")]
    if disabled_mp:
        new_lessons.append({
            "type": "disable_multiphysics",
            "description": f"User disabled multiphysics: {disabled_mp}",
            "detail": "Linked physics were likely disabled too. Consider conditional multiphysics creation.",
            "items": disabled_mp,
        })
    
    # Pattern: User enabled features the converter had disabled/missing
    enabled_feats = [n for n in all_enables if n.startswith("physics.")]
    if enabled_feats:
        new_lessons.append({
            "type": "enable_feature",
            "description": f"User enabled features: {enabled_feats}",
            "detail": "Converter should create these active.",
            "items": enabled_feats,
        })
    
    # Pattern: User added materials
    added_mats = {k: v for k, v in all_adds.items() if k.startswith("mat.")}
    if added_mats:
        new_lessons.append({
            "type": "add_material",
            "description": f"User manually added materials: {added_mats}",
            "detail": "Converter should create these automatically.",
            "items": added_mats,
        })
    
    # Pattern: User changed selections
    if all_selection_changes:
        new_lessons.append({
            "type": "selection_fix",
            "description": f"User corrected selections on {len(all_selection_changes)} nodes",
            "detail": all_selection_changes,
        })
    
    # Pattern: User changed study step active status
    study_changes = [n for n in all_disables if n.startswith("study.")]
    if study_changes:
        new_lessons.append({
            "type": "study_config",
            "description": f"User disabled study steps: {study_changes}",
            "detail": "Consider not creating these steps, or creating them disabled.",
            "items": study_changes,
        })
    
    # Add new lessons with timestamp
    for lesson in new_lessons:
        lesson["session"] = kb["session_count"]
        lesson["timestamp"] = datetime.now().isoformat()
        kb["lessons"].append(lesson)
    
    save_knowledge_base(kb)
    
    return new_lessons


def tool_get_knowledge():
    """
    MCP Tool: Read the accumulated knowledge base.
    Returns all lessons learned from past sessions.
    """
    return load_knowledge_base()


def tool_add_lesson(lesson_type, description, detail=None):
    """
    MCP Tool: Manually add a lesson to the knowledge base.
    """
    kb = load_knowledge_base()
    lesson = {
        "type": lesson_type,
        "description": description,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
        "source": "manual",
    }
    kb["lessons"].append(lesson)
    save_knowledge_base(kb)
    return {"status": "ok", "lesson": lesson}


# ═══════════════════════════════════════════════════════════════════════
# WATCH MODE v2 — With noise filtering, playbook, and learning
# ═══════════════════════════════════════════════════════════════════════

def watch_mode(interval=5, log_file=None):
    """
    Continuously monitor the COMSOL model and report changes.
    
    v2 improvements:
    - Filters reconnect noise (model briefly disappears during save/reload)
    - Filters builder_* coupling churn (COMSOL thermo regenerates these)
    - On exit: generates a clean playbook and learns lessons for the KB
    
    Args:
        interval: seconds between snapshots (default 5)
        log_file: optional path to write change log JSON
    """
    import time
    
    playbook_file = (log_file or "comsol_changes.json").replace(
        ".json", "_playbook.json")
    if not log_file:
        log_file = "comsol_changes.json"
    
    print(f"\n{'█'*60}")
    print(f"██  COMSOL LIVE WATCH MODE v2")
    print(f"██  Polling every {interval}s — Ctrl+C to stop")
    print(f"██  Noise filtering: ON | Learning: ON")
    print(f"{'█'*60}")
    
    # Initial snapshot
    print(f"\n  Taking initial snapshot...")
    prev_snap = take_deep_snapshot()
    
    if "_error" in prev_snap:
        print(f"  ✗ {prev_snap['_error']}")
        return
    
    # Save baseline for end-of-session comparison
    baseline_snap = dict(prev_snap)
    
    n_keys = len([k for k in prev_snap if not k.startswith("_")])
    print(f"  ✓ Baseline: {n_keys} model properties captured")
    print(f"  ✓ Model: {prev_snap.get('_model_tag', '?')}")
    print(f"  ✓ Geometry: {prev_snap.get('geom.domains', '?')} domains, "
          f"{prev_snap.get('geom.boundaries', '?')} boundaries")
    print(f"  ✓ Mesh: {prev_snap.get('mesh.elements', '?')} elements")
    print(f"  ✓ Log: {log_file}")
    print(f"  ✓ Playbook: {playbook_file}")
    print(f"  ✓ Knowledge base: {KNOWLEDGE_BASE_FILE}")
    print(f"\n  Watching for changes... (make changes in COMSOL GUI)\n")
    
    change_log = []
    poll_count = 0
    last_time = time.time()
    noise_count = 0
    disconnect_snap = None  # hold snapshot during disconnects
    
    try:
        while True:
            time.sleep(interval)
            poll_count += 1
            now = time.time()
            
            try:
                new_snap = take_deep_snapshot()
                
                # Handle disconnect: hold prev_snap steady
                if "_error" in new_snap:
                    if disconnect_snap is None:
                        disconnect_snap = prev_snap
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                              f"⚠ Connection lost — holding snapshot...")
                    continue
                
                # Reconnect: restore from pre-disconnect snapshot
                if disconnect_snap is not None:
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                          f"✓ Reconnected — diffing against pre-disconnect state")
                    prev_snap = disconnect_snap
                    disconnect_snap = None
                
                diff = diff_snapshots(prev_snap, new_snap)
                
                # Filter reconnect noise
                if is_reconnect_noise(diff):
                    noise_count += 1
                    prev_snap = new_snap
                    last_time = now
                    continue
                
                # Filter builder_* churn
                diff = filter_builder_noise(diff)
                
                elapsed = now - last_time
                total = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
                
                if total > 0:
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    print(f"  [{timestamp}] Poll #{poll_count}")
                    print(format_diff(diff, elapsed))
                    
                    change_entry = {
                        "timestamp": datetime.now().isoformat(),
                        "poll": poll_count,
                        "elapsed_sec": round(elapsed, 1),
                        "added": diff["added"],
                        "removed": diff["removed"],
                        "changed": diff["changed"],
                    }
                    change_log.append(change_entry)
                    
                    if log_file:
                        try:
                            with open(log_file, "w") as f:
                                json.dump(change_log, f, indent=2, default=str)
                        except: pass
                    
                    prev_snap = new_snap
                    last_time = now
                else:
                    if poll_count % 12 == 0:
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                              f"Poll #{poll_count} — no changes (watching...)")
            
            except Exception as e:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] ⚠ Poll error: {e}")
    
    except KeyboardInterrupt:
        print(f"\n\n{'═'*60}")
        print(f"  Watch stopped after {poll_count} polls")
        print(f"  {len(change_log)} change events recorded")
        print(f"  {noise_count} reconnect noise events filtered")
        print(f"{'═'*60}")
        
        if not change_log:
            print("  No meaningful changes detected.")
            return
        
        # Save raw log
        if log_file:
            try:
                with open(log_file, "w") as f:
                    json.dump(change_log, f, indent=2, default=str)
                print(f"\n  ✓ Raw change log: {log_file}")
            except: pass
        
        # Generate and save playbook
        playbook = generate_playbook(change_log)
        print(format_playbook(playbook))
        
        try:
            with open(playbook_file, "w") as f:
                json.dump(playbook, f, indent=2, default=str)
            print(f"\n  ✓ Playbook saved: {playbook_file}")
        except: pass
        
        # Learn from session
        print(f"\n{'─'*60}")
        print(f"  LEARNING FROM SESSION...")
        print(f"{'─'*60}")
        
        lessons = learn_from_session(change_log, playbook)
        if lessons:
            for lesson in lessons:
                print(f"  📝 [{lesson['type']}] {lesson['description']}")
            print(f"\n  ✓ {len(lessons)} lessons saved to {KNOWLEDGE_BASE_FILE}")
        else:
            print("  No new lessons extracted.")
        
        # Generate full session diff (baseline → final)
        try:
            final_snap = take_deep_snapshot()
            if "_error" not in final_snap:
                full_diff = diff_snapshots(baseline_snap, final_snap)
                full_diff = filter_builder_noise(full_diff)
                total = (len(full_diff["added"]) + len(full_diff["removed"]) 
                         + len(full_diff["changed"]))
                if total > 0:
                    session_summary = {
                        "session_timestamp": datetime.now().isoformat(),
                        "baseline_to_final_diff": full_diff,
                        "playbook": playbook,
                        "lessons": lessons,
                    }
                    summary_file = (log_file or "comsol_changes.json").replace(
                        ".json", "_session_summary.json")
                    with open(summary_file, "w") as f:
                        json.dump(session_summary, f, indent=2, default=str)
                    print(f"  ✓ Session summary: {summary_file}")
                    print(f"    (Paste this file into a new Claude chat for full context)")
        except: pass
        
        print(f"\n{'═'*60}\n")


# ═══════════════════════════════════════════════════════════════════════
# MCP TOOL: WATCH SNAPSHOT (for Claude to call periodically)
# ═══════════════════════════════════════════════════════════════════════

_last_mcp_snapshot = None

def tool_watch_snapshot():
    """
    MCP Tool: Take a snapshot and diff against the last one.
    Call this periodically to detect what the user changed in COMSOL GUI.
    Returns the diff (added/removed/changed) or "no_changes".
    Automatically filters reconnect noise and builder_* churn.
    """
    global _last_mcp_snapshot
    
    new_snap = take_deep_snapshot()
    if "_error" in new_snap:
        return {"error": new_snap["_error"]}
    
    if _last_mcp_snapshot is None:
        _last_mcp_snapshot = new_snap
        n_keys = len([k for k in new_snap if not k.startswith("_")])
        return {"status": "baseline_captured", "properties_tracked": n_keys}
    
    diff = diff_snapshots(_last_mcp_snapshot, new_snap)
    
    # Filter noise
    if is_reconnect_noise(diff):
        _last_mcp_snapshot = new_snap
        return {"status": "reconnect_noise_filtered"}
    
    diff = filter_builder_noise(diff)
    total = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
    
    if total == 0:
        return {"status": "no_changes"}
    
    _last_mcp_snapshot = new_snap
    return {
        "status": "changes_detected",
        "total_changes": total,
        "added": diff["added"],
        "removed": diff["removed"],
        "changed": diff["changed"],
    }


def tool_full_snapshot():
    """
    MCP Tool: Return the complete current model state as a flat dict.
    Useful for Claude to understand the full model at any point.
    """
    return take_deep_snapshot()


# ═══════════════════════════════════════════════════════════════════════
# TOOL: GUI INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════

GAS_COMPOSITIONS = [
    ("61He 36.5H2 2.5CH4",  {"He": 0.61,  "H2": 0.365, "CH4": 0.025, "N2": 0.0}),
    ("97.5H2 2.5CH4",       {"He": 0.0,   "H2": 0.975, "CH4": 0.025, "N2": 0.0}),
    ("10N2 51He 36.5H2",    {"He": 0.51,  "H2": 0.365, "CH4": 0.025, "N2": 0.10}),
    ("31N2 30He H2 2.5CH4", {"He": 0.3,   "H2": 0.365, "CH4": 0.025, "N2": 0.31}),
    ("61N2 36.5H2 2.5CH4",  {"He": 0.0,   "H2": 0.365, "CH4": 0.025, "N2": 0.61}),
]


def tool_gui_instructions():
    """
    MCP Tool: Get the current thermodynamics GUI status and instructions
    for the 3 manual steps required after conversion.

    Returns whether thermodynamics has been initialized (Generate Material done)
    and what steps remain.
    """
    client, model, err_msg = get_java_model()
    if err_msg:
        return {"error": err_msg}

    jm = model.java
    model_tag = str(jm.tag())

    # Check for generated gas materials (tags like pp1mat1, pp1mat2…)
    gas_mats = []
    switches = []
    try:
        comp = jm.component("comp1")
        mat_tags = [str(t) for t in list(comp.material().tags())]
        gas_mats = [t for t in mat_tags if "pp" in t and t != "pp1"]
        for t in mat_tags:
            try:
                if str(comp.material(t).getType()) == "Switch":
                    switches.append(t)
            except Exception:
                pass
    except Exception as e:
        return {"error": f"Cannot inspect materials: {e}"}

    thermo_initialized = len(gas_mats) > 0
    switch_present = len(switches) > 0

    steps_done = []
    steps_needed = []

    if thermo_initialized:
        steps_done.append("Generate Material (gas materials found)")
    else:
        steps_needed.append("Right-click Thermodynamic System 1 (pp1) → Define System")
        steps_needed.append("Right-click pp1 → Generate Material")

    if switch_present:
        steps_done.append(f"Material Switch found: {switches}")
    else:
        steps_needed.append("Material Switch not found — Generate Material may be incomplete")

    if thermo_initialized:
        # Check if mole fractions are set (non-trivial to verify via API, just note it)
        steps_needed.append(
            "Verify mole fractions are set for each gas composition (API cannot check)"
        )

    return {
        "model": model_tag,
        "thermodynamics_initialized": thermo_initialized,
        "generated_gas_materials": gas_mats,
        "material_switches": switches,
        "steps_done": steps_done,
        "steps_needed": steps_needed,
        "gas_compositions": [
            {"name": name, "fractions": fracs}
            for name, fracs in GAS_COMPOSITIONS
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE CLI
# ═══════════════════════════════════════════════════════════════════════

def pretty(data):
    print(json.dumps(data, indent=2, default=str))

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    # Watch mode
    if cmd == "watch":
        interval = 5
        log_file = "comsol_changes.json"
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
            elif arg.startswith("--log="):
                log_file = arg.split("=")[1]
            elif arg == "--no-log":
                log_file = None
        watch_mode(interval=interval, log_file=log_file)
        return
    
    # Knowledge base commands
    if cmd == "kb":
        subcmd = sys.argv[2] if len(sys.argv) > 2 else "show"
        if subcmd == "show":
            print("\n── Knowledge Base ──")
            pretty(load_knowledge_base())
        elif subcmd == "lessons":
            kb = load_knowledge_base()
            print(f"\n── {len(kb['lessons'])} Lessons Learned ──")
            for i, lesson in enumerate(kb["lessons"], 1):
                print(f"  {i}. [{lesson['type']}] {lesson['description']}")
                if lesson.get("detail"):
                    print(f"     → {lesson['detail']}")
        elif subcmd == "clear":
            save_knowledge_base({
                "version": 1,
                "created": datetime.now().isoformat(),
                "lessons": [],
                "converter_rules": [],
                "manual_steps": [],
                "session_count": 0,
            })
            print("  ✓ Knowledge base cleared")
        return
    
    # Playbook from existing log
    if cmd == "playbook":
        log_path = sys.argv[2] if len(sys.argv) > 2 else "comsol_changes.json"
        try:
            with open(log_path) as f:
                change_log = json.load(f)
            playbook = generate_playbook(change_log)
            print(format_playbook(playbook))
        except Exception as e:
            print(f"  ✗ Cannot load {log_path}: {e}")
        return
    
    print(f"\n{'═'*60}")
    print(f"  COMSOL Live Monitor — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'═'*60}\n")
    
    if cmd in ("status", "all"):
        print("── Model Status ──")
        pretty(tool_model_status())
    
    if cmd in ("errors", "all"):
        print("\n── Solver Errors ──")
        pretty(tool_solver_errors())
    
    if cmd in ("physics", "all"):
        print("\n── Physics ──")
        tag = sys.argv[2] if len(sys.argv) > 2 else None
        pretty(tool_inspect_physics(tag))
    
    if cmd in ("materials", "all"):
        print("\n── Materials ──")
        pretty(tool_inspect_materials())
    
    if cmd in ("definitions", "defs", "all"):
        print("\n── Definitions ──")
        pretty(tool_inspect_definitions())
    
    if cmd in ("geometry", "geom", "all"):
        print("\n── Geometry ──")
        pretty(tool_geometry_info())
    
    if cmd in ("snapshot",):
        print("\n── Full Snapshot ──")
        pretty(take_deep_snapshot())

    if cmd in ("gui", "gui_instructions"):
        print("\n── GUI Instructions / Thermodynamics Status ──")
        pretty(tool_gui_instructions())

    if cmd == "get" and len(sys.argv) >= 4:
        pretty(tool_get_property(sys.argv[2], sys.argv[3]))
    
    if cmd == "set" and len(sys.argv) >= 5:
        pretty(tool_set_property(sys.argv[2], sys.argv[3], sys.argv[4]))
    
    if cmd == "help":
        print("""
  Usage:
    python comsol_live_monitor.py                  # full status
    python comsol_live_monitor.py status            # model overview
    python comsol_live_monitor.py watch              # live watch mode
    python comsol_live_monitor.py watch --interval=3 # faster polling
    python comsol_live_monitor.py snapshot           # full flat snapshot
    python comsol_live_monitor.py physics spf        # inspect one interface
    python comsol_live_monitor.py kb show            # view knowledge base
    python comsol_live_monitor.py kb lessons         # list lessons learned
    python comsol_live_monitor.py kb clear            # reset knowledge base
    python comsol_live_monitor.py gui                 # check GUI step status
    python comsol_live_monitor.py playbook            # generate from last log
    python comsol_live_monitor.py get PATH PROP      # read a property
    python comsol_live_monitor.py set PATH PROP VAL  # write a property
        """)


if __name__ == "__main__":
    main()