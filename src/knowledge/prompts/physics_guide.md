# Physics Interfaces Guide

This guide covers the most commonly used physics interfaces in COMSOL Multiphysics and how to set them up using the MCP tools.

## Overview

COMSOL physics interfaces define the governing equations and boundary conditions for simulations. A single model can have multiple physics interfaces, and they can be coupled together for multiphysics simulations.

## AC/DC Module

### Electrostatics (es)

For static electric fields and capacitance calculations.

**Key Features:**
- Electric potential distribution
- Capacitance calculation
- Electric field strength
- Energy storage

**Boundary Conditions:**
- `Ground`: Zero potential (V = 0)
- `ElectricPotential`: Specified voltage (V = V0)
- `SurfaceChargeDensity`: Surface charge (σ)
- `ZeroCharge`: Zero normal displacement (n·D = 0)
- `Terminal`: For terminal-based capacitance

**Example:**
```
physics_add_electrostatics()
physics_configure_boundary("Electrostatics", "Ground", [1])
physics_configure_boundary("Electrostatics", "ElectricPotential", [2], {"V0": "10[V]"})
```

**Useful Expressions:**
- `es.normE` - Electric field magnitude
- `es.normD` - Electric displacement magnitude
- `es.V` - Electric potential
- `es.intWe` - Electric energy (for integration)

### Electric Currents (ec)

For DC current conduction.

**Key Features:**
- Current density distribution
- Resistance calculation
- Power dissipation

**Boundary Conditions:**
- `Ground`: Zero potential
- `ElectricPotential`: Specified voltage
- `NormalCurrentDensity`: Specified current
- `Terminal`: For circuit connections

## Structural Mechanics Module

### Solid Mechanics (solid)

For stress, strain, and deformation analysis.

**Key Features:**
- Stress distribution
- Displacement fields
- Modal analysis
- Contact mechanics

**Boundary Conditions:**
- `Fixed`: Fixed constraint (u = 0)
- `Roller`: Roller constraint (normal displacement = 0)
- `Symmetry`: Symmetry plane
- `BoundaryLoad`: Applied force/pressure
- `Displacement`: Prescribed displacement

**Example:**
```
physics_add_solid_mechanics()
physics_configure_boundary("Solid Mechanics", "Fixed", [1])
physics_configure_boundary("Solid Mechanics", "BoundaryLoad", [2], {"F_total": "1000[N]"})
```

**Useful Expressions:**
- `solid.mises` - Von Mises stress
- `solid.disp` - Displacement magnitude
- `solid.u`, `solid.v`, `solid.w` - Displacement components
- `solid.epxx` - Strain components

## Heat Transfer Module

### Heat Transfer in Solids (ht)

For temperature distribution and thermal analysis.

**Key Features:**
- Temperature distribution
- Heat flux
- Thermal gradients
- Transient thermal analysis

**Boundary Conditions:**
- `Temperature`: Fixed temperature (T = T0)
- `HeatFlux`: Specified heat flux
- `ConvectiveHeatFlux`: Convection (q = h·(T - T∞))
- `Radiation`: Radiation heat transfer
- `Symmetry`: Symmetry (adiabatic)
- `ThermalInsulation`: No heat flux

**Example:**
```
physics_add_heat_transfer()
physics_configure_boundary("Heat Transfer", "Temperature", [1], {"T0": "300[K]"})
physics_configure_boundary("Heat Transfer", "ConvectiveHeatFlux", [2], {"h": "10[W/(m^2*K)]", "Text": "293[K]"})
```

**Useful Expressions:**
- `T` - Temperature
- `ht.qx`, `ht.qy`, `ht.qz` - Heat flux components
- `ht.gradTx` - Temperature gradient
- `ht.Qh` - Heat source

## Fluid Flow Module

### Laminar Flow (spf)

For incompressible fluid flow at low Reynolds numbers.

**Key Features:**
- Velocity field
- Pressure distribution
- Flow rate calculations
- Drag/lift forces

**Boundary Conditions:**
- `Wall`: No-slip wall
- `Inlet`: Velocity or mass flow inlet
- `Outlet`: Pressure outlet
- `Symmetry`: Symmetry plane
- `Slip`: Slip wall

**Example:**
```
physics_add_laminar_flow()
physics_configure_boundary("Laminar Flow", "Inlet", [1], {"U0": "1[m/s]"})
physics_configure_boundary("Laminar Flow", "Outlet", [2], {"p0": "0[Pa]"})
```

**Useful Expressions:**
- `u`, `v`, `w` - Velocity components
- `p` - Pressure
- `spf.U` - Velocity magnitude
- `spf.rho` - Density

## Multiphysics Couplings

### Thermal Stress (ts)

Couples Heat Transfer and Solid Mechanics for thermal expansion.

**Required Physics:**
1. Heat Transfer in Solids
2. Solid Mechanics

**Example:**
```
physics_add_heat_transfer()
physics_add_solid_mechanics()
multiphysics_add("ThermalStress", ["Heat Transfer", "Solid Mechanics"])
```

### Joule Heating (jh)

Couples Electric Currents and Heat Transfer for resistive heating.

**Required Physics:**
1. Electric Currents
2. Heat Transfer

**Example:**
```
physics_add("ElectricCurrents")
physics_add_heat_transfer()
multiphysics_add("JouleHeating", ["Electric Currents", "Heat Transfer"])
```

### Fluid-Structure Interaction (fsi)

Couples Fluid Flow and Solid Mechanics.

**Required Physics:**
1. Laminar Flow (or turbulent)
2. Solid Mechanics

**Example:**
```
physics_add_laminar_flow()
physics_add_solid_mechanics()
multiphysics_add("FluidStructureInteraction", ["Laminar Flow", "Solid Mechanics"])
```

## Materials

Common material properties needed for different physics:

| Physics | Required Properties |
|---------|---------------------|
| Electrostatics | Relative permittivity (εr) |
| Electric Currents | Electrical conductivity (σ) |
| Solid Mechanics | Young's modulus (E), Poisson's ratio (ν), Density (ρ) |
| Heat Transfer | Thermal conductivity (k), Specific heat (Cp), Density (ρ) |
| Laminar Flow | Density (ρ), Dynamic viscosity (μ) |

## Selection of Physics Interface

When choosing physics interfaces, consider:

1. **Dimensionality**: 2D, 2D axisymmetric, or 3D
2. **Time dependence**: Stationary or time-dependent
3. **Coupling**: Single physics or multiphysics
4. **Nonlinearity**: Linear or nonlinear material behavior
5. **Geometry complexity**: Simple shapes or imported CAD

## Study Types

Different physics require appropriate study types:

| Physics | Recommended Study |
|---------|------------------|
| Electrostatics | Stationary |
| Solid Mechanics | Stationary, Eigenfrequency |
| Heat Transfer | Stationary, Time Dependent |
| Fluid Flow | Stationary, Time Dependent |
| Multiphysics | Depends on coupling |
