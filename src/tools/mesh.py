"""Mesh tools for COMSOL MCP Server."""

from typing import Optional
from mcp.server.fastmcp import FastMCP

from .session import session_manager


def register_mesh_tools(mcp: FastMCP) -> None:
    """Register mesh tools with the MCP server."""
    
    @mcp.tool()
    def mesh_list(model_name: Optional[str] = None) -> dict:
        """
        List all mesh sequences in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of mesh sequence names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            meshes = model.meshes()
            return {
                "success": True,
                "meshes": meshes,
                "count": len(meshes),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list meshes: {str(e)}"}
    
    @mcp.tool()
    def mesh_create(
        mesh_name: Optional[str] = None,
        model_name: Optional[str] = None,
        mesh_size: int = 3
    ) -> dict:
        """
        Create and build a physics-controlled mesh sequence.

        If no mesh sequence exists, one is created automatically using a
        physics-controlled free-tetrahedral mesh. If one already exists it
        is simply (re-)built.

        Args:
            mesh_name: Mesh sequence name (default: 'mesh1')
            model_name: Model name (default: current model)
            mesh_size: COMSOL predefined size 1 (extremely fine) – 9 (extremely coarse),
                       default 3 (fine)

        Returns:
            Mesh generation status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            target = mesh_name or "mesh1"

            # Collect existing mesh sequence tags
            existing_tags = []
            for comp in jm.component():
                try:
                    existing_tags = [str(t) for t in comp.mesh().tags()]
                except Exception:
                    pass

            if target not in existing_tags:
                # Create a new physics-controlled free-tet mesh sequence
                comp = next(iter(jm.component()))
                mesh_seq = comp.mesh().create(target)
                mesh_seq.autoMeshSize(mesh_size)
                mesh_seq.run()
            else:
                # Re-run existing sequence
                model.mesh(target)

            return {
                "success": True,
                "mesh": target,
                "mesh_size_level": mesh_size,
                "message": f"Mesh '{target}' built successfully (size level {mesh_size}).",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create mesh: {str(e)}"}
    
    @mcp.tool()
    def mesh_info(
        mesh_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get information about a mesh.
        
        Args:
            mesh_name: Mesh sequence name (default: first mesh)
            model_name: Model name (default: current model)
        
        Returns:
            Mesh statistics including element counts
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            meshes = model.meshes()
            if not meshes:
                return {"success": False, "error": "No meshes defined in model."}
            
            target = mesh_name or meshes[0]
            if target not in meshes:
                return {"success": False, "error": f"Mesh not found: {target}"}
            
            mesh_node = model / "meshes" / target
            
            info = {
                "name": target,
            }
            
            try:
                java_mesh = mesh_node.java
                if hasattr(java_mesh, 'getVertex'):
                    info["num_vertices"] = java_mesh.getVertex().size()
                if hasattr(java_mesh, 'getElement'):
                    info["num_elements"] = java_mesh.getElement().size()
            except Exception:
                pass
            
            try:
                children = [child.name() for child in mesh_node.children()]
                info["features"] = children
            except Exception:
                pass
            
            return {
                "success": True,
                "mesh": info,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get mesh info: {str(e)}"}
