# COMSOL Modeling Workflow Guide

This guide describes the typical workflow for creating and running COMSOL simulations using the MCP tools.

## Basic Workflow

### 1. Session Management

```
┌─────────────────────────────────────────────────────┐
│  Start COMSOL Session                               │
│  comsol_start(cores=4)                              │
│  or                                                 │
│  comsol_connect(port=2036, host="server")           │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Load or Create Model                               │
│  model_load("existing.mph")                         │
│  or                                                 │
│  model_create("new_model")                          │
└─────────────────────────────────────────────────────┘
```

### 2. Model Setup (for new models)

```
┌─────────────────────────────────────────────────────┐
│  Define Parameters                                  │
│  param_set("L", "10[mm]")                           │
│  param_set("W", "5[mm]")                            │
│  param_set("T", "1[mm]")                            │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Create Geometry                                    │
│  geometry_add_block(size=["L", "W", "T"])           │
│  geometry_build()                                   │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Add Physics                                        │
│  physics_add_electrostatics()                       │
│  physics_configure_boundary(...)                    │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Create Mesh                                        │
│  mesh_create()                                      │
└─────────────────────────────────────────────────────┘
```

### 3. Solve and Analyze

```
┌─────────────────────────────────────────────────────┐
│  Solve                                              │
│  study_solve("stationary")                          │
│  or                                                 │
│  study_solve_async("time_dependent")                │
│  study_get_progress()                               │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Evaluate Results                                   │
│  results_evaluate("T", "K")                         │
│  results_global_evaluate("ht.Tmax", "K")            │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Export and Save                                    │
│  results_export_image("plot", "result.png")         │
│  model_save_version(description="final")            │
└─────────────────────────────────────────────────────┘
```

## Common Workflows by Application

### Electrostatics Simulation (Capacitor)

```
# 1. Start and create
comsol_start(cores=1)
model_load("capacitor_template.mph")

# 2. Modify parameters
param_set("electrode_spacing", "2[mm]")
param_set("applied_voltage", "10[V]")
param_set("dielectric_constant", "4.5")

# 3. Solve
study_solve("stationary")

# 4. Evaluate
C = results_global_evaluate("2*es.intWe/U^2", "pF")
E_max = results_evaluate("es.normE", "V/m")

# 5. Save version
model_save_version(description=f"C={C:.2f}pF")
```

### Thermal Analysis

```
# 1. Create new model
comsol_start()
model_create("heat_sink")

# 2. Parameters
param_set("base_temp", "300[K]")
param_set("heat_flux", "1000[W/m^2]")
param_set("convection_coeff", "15[W/(m^2*K)]")

# 3. Geometry
geometry_add_block(size=[0.1, 0.1, 0.01])  # Base
geometry_add_block(position=[0.01, 0.01, 0.01], size=[0.02, 0.02, 0.05])  # Fin
# Add more fins...
geometry_build()

# 4. Physics
physics_add_heat_transfer()
physics_configure_boundary("Heat Transfer", "HeatFlux", [1], {"q0": "heat_flux"})
physics_configure_boundary("Heat Transfer", "ConvectiveHeatFlux", [3,4,5], {"h": "convection_coeff"})

# 5. Mesh and solve
mesh_create()
study_solve()

# 6. Results
T_max = results_global_evaluate("ht.Tmax", "K")
results_export_image("temperature", "temp_distribution.png")
```

### Structural Analysis

```
# 1. Load model
model_load("bracket.mph")

# 2. Parameters
param_set("load_force", "1000[N]")
param_set("youngs_modulus", "200[GPa]")
param_set("poissons_ratio", "0.3")

# 3. Physics
physics_add_solid_mechanics()
physics_configure_boundary("Solid Mechanics", "Fixed", [1])
physics_configure_boundary("Solid Mechanics", "BoundaryLoad", [5], {"F_total": "load_force"})

# 4. Solve
mesh_create()
study_solve()

# 5. Evaluate
stress = results_evaluate("solid.mises", "MPa")
displacement = results_global_evaluate("solid.maxDisp", "mm")
```

### Parametric Sweep

```
# 1. Setup model
model_load("sensitivity_study.mph")

# 2. Configure sweep
param_sweep_setup("electrode_spacing", [1, 2, 3, 4, 5])
# Or continuous range: param_sweep_setup("voltage", ["1[V]", "5[V]", "10[V]", "20[V]"])

# 3. Solve
study_solve("parametric")

# 4. Analyze results
for i in range(1, 6):
    C = results_global_evaluate("2*es.intWe/U^2", "pF", outer=i)
    print(f"Spacing {i}mm: C = {C:.3f} pF")

# 5. Export
results_export_data("sweep_data", "parametric_results.txt")
```

### Time-Dependent Simulation

```
# 1. Setup
model_load("transient_heat.mph")

# 2. Solve asynchronously
study_solve_async("time_dependent")

# 3. Monitor progress
while True:
    progress = study_get_progress()
    print(f"Progress: {progress['progress']*100:.1f}%")
    if progress['status'] in ['completed', 'failed']:
        break
    time.sleep(10)

# 4. Analyze time history
indices, times = results_inner_values("time_dependent")
for t, idx in zip(times[-5:], indices[-5:]):  # Last 5 time steps
    T_max = results_global_evaluate("ht.Tmax", "K", inner=idx)
    print(f"t={t}s: T_max={T_max:.1f}K")
```

### Multiphysics (Thermal-Stress)

```
# 1. Create model
model_create("thermal_stress_analysis")

# 2. Geometry
geometry_add_cylinder(radius="r", height="h")
geometry_build()

# 3. Add multiple physics
physics_add_heat_transfer()
physics_configure_boundary("Heat Transfer", "Temperature", [1], {"T0": "T_hot"})
physics_configure_boundary("Heat Transfer", "Temperature", [2], {"T0": "T_cold"})

physics_add_solid_mechanics()
physics_configure_boundary("Solid Mechanics", "Fixed", [1])

# 4. Add coupling
multiphysics_add("ThermalStress", ["Heat Transfer", "Solid Mechanics"])

# 5. Solve
mesh_create()
study_solve()

# 6. Results
T = results_evaluate("T", "K")
stress = results_evaluate("solid.mises", "MPa")
displacement = results_evaluate("solid.disp", "mm")
```

## Version Control Workflow

```
# Save versions at key milestones
model_save_version(description="initial_geometry")
# ... modify geometry ...
model_save_version(description="geometry_final")

# ... add physics ...
model_save_version(description="physics_configured")

# ... after solving ...
model_save_version(description="solved_baseline")

# ... parameter variation ...
model_save_version(description="param_optimized_v1")
```

## Troubleshooting Common Issues

### Geometry Build Fails
- Check for overlapping features
- Ensure all parameters are defined
- Verify coordinate systems

### Mesh Generation Fails
- Refine geometry details
- Check for very small features
- Try different mesh size settings

### Solver Convergence Issues
- Refine mesh quality
- Check boundary conditions
- Use appropriate solver settings
- Consider scaling of variables

### Memory Issues
- Reduce mesh density
- Use symmetry to reduce domain size
- Solve on more powerful hardware
