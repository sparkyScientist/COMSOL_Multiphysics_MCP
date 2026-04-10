# COMSOL Multiphysics MCP Server

**Physics-aware MCP tooling for COMSOL via Java API**

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)

## What This Is

The first MCP server for COMSOL Multiphysics with physics-aware tooling.
Enables Claude (or any MCP client) to drive COMSOL programmatically: build
meshes, configure solvers, run parametric sweeps, and extract results with
zero GUI interaction required.

The server communicates with a running COMSOL `mphserver` process through the
[MPh](https://mph.readthedocs.io/) Python library, which wraps the COMSOL
Java API via JPype.

## Built On

Forked from [wjc9011/COMSOL_Multiphysics_MCP](https://github.com/wjc9011/COMSOL_Multiphysics_MCP) (MIT License).
That project provided the foundational MCP-to-COMSOL Java API bridge. This
project adds physics-aware mesh generation, analytic thermodynamic property
expressions, segregated solver tooling with physics-aware step grouping,
workflow memory, 2D-to-3D conversion, and a simulation-in-the-loop Bayesian
optimization pipeline for CNT reactor design.

## Novel Contributions

- **Physics-aware mesh builder**: boundary detection via `getVertexCoord()`
  and `getAdj(1,0)`, injector refinement, boundary layers, quality reporting.
  No hardcoded geometry tags.
- **Analytic gas property bypass**: density (ideal gas), viscosity (Wilke
  mixing, 3.5% max error), thermal conductivity (Mason-Saxena blend, 2.41%
  max error), Cp (NASA polynomials, 0.12% max error). 51 COMSOL variable
  expressions, zero GUI clicks per composition change.
- **Segregated solver setup**: 4-step physics-aware grouping (radiosity,
  nonisothermal flow, turbulence, wall functions).
- **Workflow memory**: `memorize_workflows.py` stores successful solver
  configurations as Digital Twin JSON recipes for reuse.
- **2D-to-3D converter**: automated axisymmetric-to-3D geometry promotion
  with CylinderSelectionMapper for selection remapping.
- **Validator and autofixer**: detects and repairs common model errors
  (empty selections, material assignment, multiphysics dependency conflicts).
- **ARES-Sim bridge**: connects multi-objective Bayesian optimization output
  directly to COMSOL CFD validation (gRPC protocol).

## Architecture

```
                        MCP Protocol
Claude / MCP Client  ──────────────>  MCP Server (src/server.py)
                                            |
                                      Tools Layer
                                    (src/tools/*.py)
                                            |
                                      MPh 1.3.1
                                      (JPype bridge)
                                            |
                                   COMSOL mphserver
                                    (port 2036)
                                            |
                                      .mph model

ARES-Sim BO  ──>  comsol_bridge  ──>  MPh layer (same connection)
```

## Tool Reference

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `mesh_reactor_2d` | Build 2D axisymmetric mesh with physics-aware sizing | `model_tag`, `refinement_level` |
| `mesh_reactor_3d` | Build 3D tetrahedral mesh with injector refinement | `model_tag`, `bore_hmax`, `reactor_hmax` |
| `mesh_quality_report` | Report element count, quality stats, type breakdown | `model_tag` |
| `mesh_refine_local` | Refine mesh in specific domains or boundaries | `model_tag`, `domain_ids`, `hmax` |
| `mesh_boundary_layer` | Add boundary layer mesh on selected boundaries | `model_tag`, `boundary_ids`, `num_layers` |
| `solver_segregated_reactor` | Configure segregated solver with physics grouping | `model_tag`, `physics_list` |
| `solver_fully_coupled` | Configure fully coupled solver | `model_tag`, `damping` |
| `solver_parametric_sweep` | Set up parameter sweep study | `model_tag`, `param_name`, `values` |
| `solver_convergence_monitor` | Monitor solver convergence in real time | `model_tag` |
| `solver_diagnostics` | Diagnose solver failures and suggest fixes | `model_tag` |
| `apply_analytic_properties` | Apply analytic gas property expressions | `model_tag`, `composition` |
| `memorize_workflow` | Capture model structure as Digital Twin JSON | `model_tag` |
| `convert_2d_to_3d` | Convert 2D axisymmetric recipe to 3D model | `recipe_file` |
| `validate_model` | Check model for selection, material, mesh errors | `model_tag` |
| `autofix_model` | Auto-repair detected validation errors | `model_tag`, `report` |

## Installation

### Prerequisites

- COMSOL Multiphysics 6.3 or later
- Python 3.12 (ARM64-native on Apple Silicon)
- conda (Miniconda or Anaconda)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/sparkyScientist/COMSOL_Multiphysics_MCP.git
cd COMSOL_Multiphysics_MCP

# 2. Create conda environment
conda env create -f environment.yml
conda activate comsol-mcp

# 3. Configure
cp .env.example .env
# Edit .env with your COMSOL path and port

# 4. Start COMSOL mphserver (in a separate terminal)
$COMSOL_BIN mphserver -port 2036 -login auto

# 5. Verify connection
python -c "import mph; c=mph.Client(port=2036); print('Connected:', c.names())"
```

### MCP Client Configuration

Add to your MCP client settings (e.g., Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "comsol": {
      "command": "python",
      "args": ["src/server.py"],
      "cwd": "/path/to/COMSOL_Multiphysics_MCP"
    }
  }
}
```

## Quick Start

```python
import mph

# Connect to running mphserver
client = mph.Client(port=2036)

# Load a model
model = client.load("my_reactor.mph")

# The MCP tools handle the rest:
# - mesh_reactor_3d builds a physics-aware mesh
# - solver_segregated_reactor configures the solver
# - solver_parametric_sweep runs composition sweeps
# - Results are extracted automatically
```

## Validated On

Developed and validated on 2D and 3D FCCVD carbon nanotube reactor models
(vertical downflow, horizontal) with nonisothermal flow, k-epsilon
turbulence, surface-to-surface radiation, and multi-component He/N2/CH4/H2
gas mixtures. Analytic property accuracy validated against COMSOL
Thermodynamics at 5 gas compositions (0-61% He by mole).

## Citation

If you use this software in your research, please cite:

```bibtex
@software{junnarkar2026comsol_mcp,
  author    = {Junnarkar, Jui},
  title     = {COMSOL Multiphysics MCP Server},
  version   = {0.1.0},
  year      = {2026},
  url       = {https://github.com/sparkyScientist/COMSOL_Multiphysics_MCP},
  doi       = {10.5281/zenodo.XXXXXXX}
}
```

See [CITATION.cff](CITATION.cff) for machine-readable citation metadata.

## License

GPL-3.0. See [LICENSE](LICENSE).

Upstream portions from [wjc9011/COMSOL_Multiphysics_MCP](https://github.com/wjc9011/COMSOL_Multiphysics_MCP) retain their original MIT License attribution.
