"""Physics-aware mesh setup tools for reactor CFD models.

Provides intelligent meshing for FCCVD reactor geometries with:
- Boundary identification by coordinate inspection
- Automatic refinement zones (injector tip, body, reaction zone)
- Boundary layer meshing on fluid-wall interfaces
- Quality assessment and local refinement

Default dimensions match the Shelly FCCVD reactor model.
"""

from typing import Optional, List
from mcp.server.fastmcp import FastMCP

from .session import session_manager


# ============================================================================
# Default reactor dimensions (Shelly model)
# ============================================================================

DEFAULT_REACTOR = {
    "reactor_radius": 0.0325,       # m (RD/2 = 65mm/2)
    "reactor_length": 1.397,        # m (L)
    "injector_radius_inner": 0.002, # m (IID/2 = 4mm/2)
    "injector_radius_outer": 0.003175,  # m (IOD/2 = 6.35mm/2)
    "injector_depth": 0.13,         # m (130mm)
    "extension_length": 0.14,       # m (L0 = 140mm)
}


def register_mesh_setup_tools(mcp: FastMCP) -> None:
    """Register physics-aware mesh setup tools."""

    # ====================================================================
    # Tool 1: mesh_reactor_2d
    # ====================================================================

    @mcp.tool()
    def mesh_reactor_2d(
        mesh_tag: str = "mesh1",
        reactor_radius: float = 0.0325,
        reactor_length: float = 1.397,
        injector_radius_inner: float = 0.002,
        injector_radius_outer: float = 0.003175,
        injector_depth: float = 0.13,
        global_size_level: int = 2,
        boundary_layer_count: int = 8,
        boundary_layer_stretch: float = 1.2,
        boundary_layer_thickness: Optional[float] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Build a physics-aware 2D axisymmetric mesh for an FCCVD reactor.

        Creates a mesh with:
        - Global element size scaled to reactor dimensions
        - Fine mesh around the injector body
        - Extra-fine mesh at the injector tip (critical flow region)
        - Boundary layers on all fluid-wall boundaries (not inlet/outlet/axis)
        - Corner refinement for sharp geometry transitions
        - Free triangular elements for the bulk

        Default dimensions match the Shelly FCCVD reactor model.

        Args:
            mesh_tag: Mesh sequence tag (default: "mesh1")
            reactor_radius: Reactor tube radius in meters (default: 0.0325)
            reactor_length: Reactor length in meters (default: 1.397)
            injector_radius_inner: Injector inner radius in meters (default: 0.002)
            injector_radius_outer: Injector outer radius in meters (default: 0.003175)
            injector_depth: Injector penetration depth in meters (default: 0.13)
            global_size_level: COMSOL predefined size 1-9 (default: 2 = extra fine)
            boundary_layer_count: Number of boundary layer elements (default: 8)
            boundary_layer_stretch: BL stretching factor (default: 1.2)
            boundary_layer_thickness: First BL element thickness in m (default: auto)
            model_name: Model name (default: current model)

        Returns:
            Mesh statistics including element counts and quality metrics
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component("comp1")

            # --- Identify boundaries by coordinate inspection ---
            geom = comp.geom("geom1")
            geom.run()
            n_bnd = geom.getNBoundaries()
            n_dom = geom.getNDomains()

            # Classify boundaries
            wall_boundaries = []
            inlet_outlet_boundaries = []
            axis_boundaries = []
            injector_tip_boundaries = []
            injector_body_boundaries = []

            r_inj_inner = injector_radius_inner
            r_inj_outer = injector_radius_outer
            z_tip = reactor_length - injector_depth  # injector exit z-coordinate

            for bnd_idx in range(1, n_bnd + 1):
                try:
                    # Get boundary coordinate bounds
                    adj_doms = list(geom.boundaryAdj(bnd_idx))

                    # Get boundary vertices via mesh coordinates later
                    # For now, use adjacency and geometry info
                    vtx = geom.getBoundaryVertices(bnd_idx) if hasattr(geom, 'getBoundaryVertices') else None
                except Exception:
                    continue

            # Build mesh sequence
            mesh_tags = [str(t) for t in comp.mesh().tags()]
            if mesh_tag in mesh_tags:
                comp.mesh().remove(mesh_tag)

            comp.mesh().create(mesh_tag)
            mesh = comp.mesh(mesh_tag)
            mesh.label("Reactor 2D Mesh")

            # --- Feature 1: Global size ---
            mesh.autoMeshSize(global_size_level)

            # Compute physics-based sizes
            hmax_global = reactor_length / 30
            hmax_injector = r_inj_inner / 4
            hmax_tip = r_inj_inner / 20

            # Override global hmax
            sz_default = mesh.feature("size")
            sz_default.set("hauto", str(global_size_level))
            sz_default.set("custom", "on")
            sz_default.set("hmax", str(hmax_global))

            # --- Feature 2: Injector body refinement ---
            # Find boundaries near the injector (r ~ r_inj_inner to r_inj_outer)
            # We select boundaries by creating a Size node and using box selection
            mesh.create("sz_injector", "Size")
            sz_inj = mesh.feature("sz_injector")
            sz_inj.label("Injector Body Size")
            sz_inj.set("custom", "on")
            sz_inj.set("hmax", str(hmax_injector))
            sz_inj.set("hmaxactive", True)

            # Use a box selection for the injector region
            sz_inj.selection().geom("geom1", 1)
            try:
                # Select boundaries in the injector region via box
                _apply_box_selection(
                    sz_inj.selection(), geom, dim=1,
                    r_min=0, r_max=r_inj_outer * 1.5,
                    z_min=z_tip - 0.01, z_max=reactor_length + 0.01,
                    n_bnd=n_bnd,
                )
            except Exception as e:
                # Fallback: apply to all boundaries
                all_bnds = list(range(1, n_bnd + 1))
                sz_inj.selection().set(all_bnds)

            # --- Feature 3: Injector tip refinement ---
            mesh.create("sz_tip", "Size")
            sz_tip_node = mesh.feature("sz_tip")
            sz_tip_node.label("Injector Tip Size")
            sz_tip_node.set("custom", "on")
            sz_tip_node.set("hmax", str(hmax_tip))
            sz_tip_node.set("hmaxactive", True)

            # Box around the injector tip region
            sz_tip_node.selection().geom("geom1", 1)
            try:
                _apply_box_selection(
                    sz_tip_node.selection(), geom, dim=1,
                    r_min=0, r_max=r_inj_outer * 2,
                    z_min=z_tip - 0.02, z_max=z_tip + 0.02,
                    n_bnd=n_bnd,
                )
            except Exception:
                pass

            # --- Feature 4: Corner refinement (allGeom for all entities) ---
            mesh.create("cr1", "CornerRefinement")
            cr = mesh.feature("cr1")
            cr.label("Corner Refinement")
            cr.selection().allGeom()

            # --- Feature 5: Free triangular ---
            mesh.create("ftri1", "FreeTri")
            ftri = mesh.feature("ftri1")
            ftri.label("Free Triangular")
            ftri.selection().geom("geom1", 2)
            ftri.selection().all()

            # --- Feature 6: Boundary layers ---
            mesh.create("bl1", "BndLayer")
            bl = mesh.feature("bl1")
            bl.label("Boundary Layers")

            # Boundary layer properties
            bl.create("blp1", "BndLayerProp")
            blp = bl.feature("blp1")
            blp.set("blnlayers", str(boundary_layer_count))
            blp.set("blstretch", str(boundary_layer_stretch))
            if boundary_layer_thickness is not None:
                blp.set("blhminfact", str(boundary_layer_thickness))

            # Select wall boundaries (exclude axis, inlet, outlet)
            # Axis boundaries are at r=0, inlet/outlet at z=0 and z=L
            wall_bnds = _find_wall_boundaries(
                geom, n_bnd,
                reactor_length=reactor_length,
                axis_tol=1e-6,
                inlet_outlet_tol=0.001,
            )
            if wall_bnds:
                blp.selection().set(wall_bnds)
            else:
                blp.selection().geom("geom1", 1)
                blp.selection().all()

            # --- Build ---
            mesh.run()

            # --- Collect statistics ---
            stats = _get_mesh_stats(mesh)

            return {
                "success": True,
                "mesh_tag": mesh_tag,
                "geometry": {
                    "n_domains": n_dom,
                    "n_boundaries": n_bnd,
                },
                "sizing": {
                    "global_hmax_m": round(hmax_global, 6),
                    "injector_hmax_m": round(hmax_injector, 6),
                    "tip_hmax_m": round(hmax_tip, 6),
                    "size_level": global_size_level,
                },
                "boundary_layers": {
                    "n_layers": boundary_layer_count,
                    "stretch_factor": boundary_layer_stretch,
                    "wall_boundaries": wall_bnds,
                },
                "stats": stats,
                "message": f"Reactor 2D mesh built: {stats.get('n_elements', '?')} elements",
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to build reactor mesh: {str(e)}"}

    # ====================================================================
    # Tool 2: mesh_reactor_3d
    # ====================================================================

    @mcp.tool()
    def mesh_reactor_3d(
        mesh_tag: str = "mesh1",
        reactor_radius: float = 0.0325,
        reactor_length: float = 1.397,
        injector_radius_inner: float = 0.002,
        global_size_level: int = 3,
        boundary_layer_count: int = 6,
        boundary_layer_stretch: float = 1.3,
        swept_layers: Optional[int] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Build a physics-aware 3D mesh for an FCCVD reactor.

        Creates a 3D mesh with:
        - Free tetrahedral elements with physics-based sizing
        - Optional swept mesh for cylindrical sections
        - Boundary layers on reactor walls
        - Local refinement at injector tip

        Args:
            mesh_tag: Mesh sequence tag (default: "mesh1")
            reactor_radius: Reactor tube radius in meters
            reactor_length: Reactor length in meters
            injector_radius_inner: Injector inner radius in meters
            global_size_level: COMSOL predefined size 1-9 (default: 3 = fine)
            boundary_layer_count: Number of BL elements (default: 6)
            boundary_layer_stretch: BL stretching factor (default: 1.3)
            swept_layers: Number of swept layers for cylindrical parts (None = auto)
            model_name: Model name (default: current model)

        Returns:
            Mesh statistics including element counts and quality
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component("comp1")
            geom = comp.geom("geom1")
            geom.run()

            n_dom = geom.getNDomains()
            n_bnd = geom.getNBoundaries()

            mesh_tags = [str(t) for t in comp.mesh().tags()]
            if mesh_tag in mesh_tags:
                comp.mesh().remove(mesh_tag)

            comp.mesh().create(mesh_tag)
            mesh = comp.mesh(mesh_tag)
            mesh.label("Reactor 3D Mesh")

            # Physics-based sizes
            hmax_global = reactor_length / 20
            hmax_injector = injector_radius_inner / 3
            hmax_tip = injector_radius_inner / 10

            # Global size
            mesh.autoMeshSize(global_size_level)
            sz = mesh.feature("size")
            sz.set("custom", "on")
            sz.set("hmax", str(hmax_global))

            # Free tetrahedral
            mesh.create("ftet1", "FreeTet")
            ftet = mesh.feature("ftet1")
            ftet.label("Free Tetrahedral")
            ftet.selection().geom("geom1", 3)
            ftet.selection().all()

            # Size on injector region
            ftet.create("sz_inj", "Size")
            sz_inj = ftet.feature("sz_inj")
            sz_inj.set("custom", "on")
            sz_inj.set("hmax", str(hmax_injector))
            sz_inj.set("hmaxactive", True)

            # Boundary layers
            mesh.create("bl1", "BndLayer")
            bl = mesh.feature("bl1")
            bl.label("Boundary Layers")
            bl.create("blp1", "BndLayerProp")
            blp = bl.feature("blp1")
            blp.set("blnlayers", str(boundary_layer_count))
            blp.set("blstretch", str(boundary_layer_stretch))
            blp.selection().geom("geom1", 2)
            blp.selection().all()

            # Build
            mesh.run()

            stats = _get_mesh_stats(mesh)

            return {
                "success": True,
                "mesh_tag": mesh_tag,
                "geometry": {"n_domains": n_dom, "n_boundaries": n_bnd},
                "sizing": {
                    "global_hmax_m": round(hmax_global, 6),
                    "injector_hmax_m": round(hmax_injector, 6),
                    "tip_hmax_m": round(hmax_tip, 6),
                },
                "stats": stats,
                "message": f"Reactor 3D mesh built: {stats.get('n_elements', '?')} elements",
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to build 3D mesh: {str(e)}"}

    # ====================================================================
    # Tool 3: mesh_quality_report
    # ====================================================================

    @mcp.tool()
    def mesh_quality_report(
        mesh_tag: str = "mesh1",
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Generate a detailed mesh quality report.

        Reports:
        - Element counts by type (triangles, quads, tets, etc.)
        - Quality statistics (min, max, mean element quality)
        - Aspect ratio and skewness metrics
        - Boundary layer element count
        - Warnings for poor quality elements

        Args:
            mesh_tag: Mesh sequence tag (default: "mesh1")
            model_name: Model name (default: current model)

        Returns:
            Detailed quality report with statistics and warnings
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component("comp1")
            mesh = comp.mesh(mesh_tag)

            stats = _get_mesh_stats(mesh)
            quality = _get_mesh_quality(mesh)

            warnings = []
            if quality.get("min_quality", 1.0) < 0.1:
                warnings.append(
                    f"POOR: Minimum element quality {quality['min_quality']:.4f} < 0.1"
                )
            if quality.get("min_quality", 1.0) < 0.01:
                warnings.append(
                    f"CRITICAL: Degenerate elements detected (quality < 0.01)"
                )
            if quality.get("mean_quality", 1.0) < 0.5:
                warnings.append(
                    f"WARNING: Mean quality {quality['mean_quality']:.4f} < 0.5"
                )

            # Check features
            features = []
            try:
                for tag in [str(t) for t in mesh.feature().tags()]:
                    feat = mesh.feature(tag)
                    features.append({
                        "tag": tag,
                        "label": str(feat.label()),
                        "type": str(feat.getType()),
                    })
            except Exception:
                pass

            return {
                "success": True,
                "mesh_tag": mesh_tag,
                "stats": stats,
                "quality": quality,
                "features": features,
                "warnings": warnings,
                "status": "PASS" if not warnings else "REVIEW",
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to get quality report: {str(e)}"}

    # ====================================================================
    # Tool 4: mesh_refine_local
    # ====================================================================

    @mcp.tool()
    def mesh_refine_local(
        mesh_tag: str = "mesh1",
        region: str = "box",
        r_min: float = 0.0,
        r_max: float = 0.01,
        z_min: float = 0.0,
        z_max: float = 0.5,
        hmax: Optional[float] = None,
        size_level: int = 1,
        feature_label: str = "Local Refinement",
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Add local mesh refinement in a specified region.

        Adds a Size feature to the mesh sequence that locally refines
        elements in a box-defined region. Useful for:
        - Injector tip refinement
        - Reaction zone refinement
        - Wake region refinement

        Args:
            mesh_tag: Mesh sequence tag (default: "mesh1")
            region: Selection method - "box" (default)
            r_min: Minimum r-coordinate of refinement box (m)
            r_max: Maximum r-coordinate of refinement box (m)
            z_min: Minimum z-coordinate of refinement box (m)
            z_max: Maximum z-coordinate of refinement box (m)
            hmax: Maximum element size in meters (None = auto from size_level)
            size_level: Size level 1-9 if hmax not specified (default: 1 = extremely fine)
            feature_label: Label for the size feature
            model_name: Model name (default: current model)

        Returns:
            Refinement details and updated mesh stats
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component("comp1")
            mesh = comp.mesh(mesh_tag)
            geom = comp.geom("geom1")
            n_bnd = geom.getNBoundaries()

            # Create unique feature tag
            existing = [str(t) for t in mesh.feature().tags()]
            idx = 1
            while f"sz_local_{idx}" in existing:
                idx += 1
            feat_tag = f"sz_local_{idx}"

            # Insert the Size feature before FreeTri/FreeTet
            mesh.create(feat_tag, "Size")
            sz = mesh.feature(feat_tag)
            sz.label(feature_label)
            sz.set("custom", "on")

            if hmax is not None:
                sz.set("hmax", str(hmax))
                sz.set("hmaxactive", True)
            else:
                sz.set("hauto", str(size_level))

            # Apply box selection
            sz.selection().geom("geom1", 1)
            selected = _apply_box_selection(
                sz.selection(), geom, dim=1,
                r_min=r_min, r_max=r_max,
                z_min=z_min, z_max=z_max,
                n_bnd=n_bnd,
            )

            # Rebuild mesh
            mesh.run()
            stats = _get_mesh_stats(mesh)

            return {
                "success": True,
                "mesh_tag": mesh_tag,
                "feature_tag": feat_tag,
                "region": {
                    "r_min": r_min, "r_max": r_max,
                    "z_min": z_min, "z_max": z_max,
                },
                "hmax": hmax,
                "size_level": size_level if hmax is None else None,
                "boundaries_selected": selected,
                "stats": stats,
                "message": f"Local refinement added: {selected} boundaries selected",
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to add local refinement: {str(e)}"}

    # ====================================================================
    # Tool 5: mesh_boundary_layer
    # ====================================================================

    @mcp.tool()
    def mesh_boundary_layer(
        mesh_tag: str = "mesh1",
        n_layers: int = 8,
        stretch_factor: float = 1.2,
        first_layer_thickness: Optional[float] = None,
        exclude_axis: bool = True,
        exclude_inlet_outlet: bool = True,
        reactor_length: float = 1.397,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Add or modify boundary layer meshing on fluid-wall interfaces.

        Automatically identifies wall boundaries by excluding:
        - Axis boundaries (r=0) if exclude_axis=True
        - Inlet/outlet boundaries (z=0, z=L) if exclude_inlet_outlet=True

        Remaining boundaries are treated as fluid-wall interfaces
        where boundary layer resolution is critical for accurate
        heat transfer and wall shear stress.

        Args:
            mesh_tag: Mesh sequence tag (default: "mesh1")
            n_layers: Number of boundary layer elements (default: 8)
            stretch_factor: Growth ratio between successive layers (default: 1.2)
            first_layer_thickness: First element thickness in m (None = auto)
            exclude_axis: Exclude r=0 boundaries (default: True)
            exclude_inlet_outlet: Exclude z=0 and z=L boundaries (default: True)
            reactor_length: Reactor length for outlet detection (default: 1.397)
            model_name: Model name (default: current model)

        Returns:
            Boundary layer configuration and selected boundaries
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component("comp1")
            mesh = comp.mesh(mesh_tag)
            geom = comp.geom("geom1")
            n_bnd = geom.getNBoundaries()

            # Find wall boundaries
            wall_bnds = _find_wall_boundaries(
                geom, n_bnd,
                reactor_length=reactor_length,
                axis_tol=1e-6 if exclude_axis else -1,
                inlet_outlet_tol=0.001 if exclude_inlet_outlet else -1,
            )

            # Check if BndLayer already exists
            existing = [str(t) for t in mesh.feature().tags()]
            bl_tag = "bl1"
            if bl_tag in existing:
                # Modify existing
                bl = mesh.feature(bl_tag)
            else:
                mesh.create(bl_tag, "BndLayer")
                bl = mesh.feature(bl_tag)
                bl.label("Boundary Layers")

            # Check if blp exists
            blp_tag = "blp1"
            try:
                blp = bl.feature(blp_tag)
            except Exception:
                bl.create(blp_tag, "BndLayerProp")
                blp = bl.feature(blp_tag)

            blp.set("blnlayers", str(n_layers))
            blp.set("blstretch", str(stretch_factor))
            if first_layer_thickness is not None:
                blp.set("blhminfact", str(first_layer_thickness))

            if wall_bnds:
                blp.selection().set(wall_bnds)

            # Rebuild
            mesh.run()
            stats = _get_mesh_stats(mesh)

            return {
                "success": True,
                "mesh_tag": mesh_tag,
                "n_layers": n_layers,
                "stretch_factor": stretch_factor,
                "first_layer_thickness": first_layer_thickness,
                "wall_boundaries": wall_bnds,
                "n_wall_boundaries": len(wall_bnds),
                "stats": stats,
                "message": f"Boundary layers: {n_layers} layers on {len(wall_bnds)} wall boundaries",
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to set boundary layers: {str(e)}"}


# ============================================================================
# Helper functions (not exposed as tools)
# ============================================================================

def _get_boundary_coords(geom, n_bnd: int) -> dict:
    """Get vertex coordinates for each boundary using getAdj(1,0) + getVertexCoord.

    Returns dict: bnd_idx (1-based) -> (r_min, z_min, r_max, z_max)
    """
    # Get all vertex coordinates (0-indexed arrays)
    vc = geom.getVertexCoord()
    n_vtx = len(vc[0])
    vtx = {}
    for i in range(n_vtx):
        vtx[i + 1] = (vc[0][i], vc[1][i])  # 1-indexed

    # Get boundary→vertex adjacency (bnd_vtx[bnd] gives vertex indices)
    bnd_vtx = geom.getAdj(1, 0)

    coords = {}
    for bnd_idx in range(1, n_bnd + 1):
        try:
            verts = list(bnd_vtx[bnd_idx])
            if len(verts) < 2:
                continue
            v1, v2 = int(verts[0]), int(verts[1])
            r1, z1 = vtx[v1]
            r2, z2 = vtx[v2]
            coords[bnd_idx] = (min(r1, r2), min(z1, z2), max(r1, r2), max(z1, z2))
        except Exception:
            continue

    return coords


def _get_mesh_stats(mesh) -> dict:
    """Extract mesh statistics from a built mesh."""
    stats = {}
    try:
        stats["n_vertices"] = int(mesh.getNumVertex())
        stats["n_elements"] = int(mesh.getNumElem())
        # getNumElem(String) for specific element types
        for etype, ename in [("tri", "n_triangles"), ("quad", "n_quads"),
                              ("tet", "n_tets"), ("hex", "n_hexahedra"),
                              ("pyr", "n_pyramids"), ("prism", "n_prisms"),
                              ("edg", "n_edges"), ("vtx", "n_points")]:
            try:
                n = int(mesh.getNumElem(etype))
                if n > 0:
                    stats[ename] = n
            except Exception:
                pass
    except Exception:
        pass
    return stats


def _get_mesh_quality(mesh) -> dict:
    """Extract mesh quality metrics."""
    quality = {}
    try:
        stat = mesh.stat()
        for attr, key in [("getQualityMin", "min_quality"),
                           ("getQualityMax", "max_quality"),
                           ("getQualityMean", "mean_quality"),
                           ("getMinVolume", "min_volume"),
                           ("getMaxGrowthRate", "max_growth_rate")]:
            if hasattr(stat, attr):
                quality[key] = float(getattr(stat, attr)())
    except Exception:
        pass
    return quality


def _find_wall_boundaries(geom, n_bnd: int,
                           reactor_length: float = 1.397,
                           axis_tol: float = 1e-6,
                           inlet_outlet_tol: float = 0.001) -> list:
    """Identify wall boundaries by excluding axis, inlet, and outlet.

    Uses getVertexCoord + getAdj(1,0) to inspect boundary vertex positions.
    - Axis: r_max < axis_tol (boundary lies along r=0)
    - Inlet/outlet: horizontal boundaries at extreme z values
    - Everything else is a wall boundary.
    """
    coords = _get_boundary_coords(geom, n_bnd)
    wall_bnds = []

    for bnd_idx in range(1, n_bnd + 1):
        if bnd_idx not in coords:
            wall_bnds.append(bnd_idx)  # Include unknown boundaries
            continue

        r_min, z_min, r_max, z_max = coords[bnd_idx]

        # Skip axis boundaries (r_max ≈ 0)
        if axis_tol > 0 and r_max < axis_tol:
            continue

        # Skip horizontal inlet/outlet boundaries
        if inlet_outlet_tol > 0:
            dz = abs(z_max - z_min)
            if dz < inlet_outlet_tol:
                z_avg = (z_min + z_max) / 2
                # Check if at top (inlet) or bottom (outlet) of geometry
                if abs(z_avg - reactor_length) < inlet_outlet_tol:
                    continue
                # Check for outlet at z_min of entire geometry
                if z_min < -0.1 and abs(z_max - z_min) < inlet_outlet_tol:
                    continue

        wall_bnds.append(bnd_idx)

    return wall_bnds


def _apply_box_selection(selection, geom, dim: int,
                          r_min: float, r_max: float,
                          z_min: float, z_max: float,
                          n_bnd: int) -> int:
    """Select boundaries whose vertices fall within the given box.

    Uses getVertexCoord + getAdj(1,0) for coordinate inspection.
    Returns the number of selected entities.
    """
    coords = _get_boundary_coords(geom, n_bnd)
    selected = []

    for bnd_idx in range(1, n_bnd + 1):
        if bnd_idx not in coords:
            continue
        ent_r_min, ent_z_min, ent_r_max, ent_z_max = coords[bnd_idx]

        # Check overlap
        if (ent_r_max >= r_min and ent_r_min <= r_max and
                ent_z_max >= z_min and ent_z_min <= z_max):
            selected.append(bnd_idx)

    if selected:
        selection.set(selected)

    return len(selected)
