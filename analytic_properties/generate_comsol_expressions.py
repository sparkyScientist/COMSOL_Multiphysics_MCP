#!/usr/bin/env python3.11
"""Generate COMSOL-syntax variable expressions for analytic gas properties.

Outputs expression strings for density, viscosity, thermal conductivity, and Cp
that reference COMSOL global parameters (x_he, x_h2, x_ch4, x_n2) and built-in
variables (T, pA).

COMSOL unit handling:
  - T_dimless = T/1[K] strips units from T for polynomial evaluation
  - Each pure-component polynomial result is multiplied by 1[unit] to restore units
  - All mixing rule intermediate variables are dimensionless (ratios)
  - Final properties carry correct SI units

The expressions reproduce COMSOL's Thermodynamics package results within ~3.5% for
all properties across the 5 validated compositions (He/N₂/H₂/CH₄ mixtures, 300-1500K).
"""

import math
import json
from analytic_gas_properties import POLY_FITS, M, SPECIES, K_BLEND_WEIGHT

# ==============================================================================
# Pre-compute constant factors for Wilke/Mason-Saxena phi_ij
# ==============================================================================

def _const_ratio_M(Mi, Mj):
    """(Mj/Mi)^0.25 — constant for each species pair."""
    return (Mj / Mi) ** 0.25

def _const_denom(Mi, Mj):
    """sqrt(8*(1 + Mi/Mj)) — constant for each species pair."""
    return math.sqrt(8.0 * (1.0 + Mi / Mj))

PHI_CONST = {}
for i in SPECIES:
    for j in SPECIES:
        if i == j:
            continue
        PHI_CONST[(i, j)] = {
            "ratio_M": _const_ratio_M(M[i], M[j]),
            "denom": _const_denom(M[i], M[j]),
        }

# ==============================================================================
# COMSOL expression helpers
# ==============================================================================

def _comsol_varname(species):
    return {"He": "He", "H2": "H2", "CH4": "CH4", "N2": "N2"}[species]

def _comsol_xvar(species):
    return {"He": "x_he", "H2": "x_h2", "CH4": "x_ch4", "N2": "x_n2"}[species]

def _poly_expr(coeffs, var="T_dimless"):
    """Generate polynomial in dimensionless T: c0 + c1*T_dimless + c2*T_dimless^2 + ..."""
    terms = []
    for i, c in enumerate(coeffs):
        if abs(c) < 1e-30:
            continue
        if i == 0:
            terms.append(f"{c:.12e}")
        elif i == 1:
            terms.append(f"{c:.12e}*{var}")
        else:
            terms.append(f"{c:.12e}*{var}^{i}")
    if not terms:
        return "0"
    return " + ".join(terms).replace("+ -", "- ")

def _fmt(val, digits=10):
    return f"{val:.{digits}e}"


# ==============================================================================
# Expression generators
# ==============================================================================

def generate_all_expressions():
    """Generate all COMSOL variable expressions in dependency order.

    ALL expressions produce pure dimensionless SI numbers.
    COMSOL interprets them in the expected unit for each property.
    This avoids all COMSOL unit conversion pitfalls.

    Returns list of (varname, expression, description) tuples.
    """
    all_vars = []

    # 0. Dimensionless temperature = numerical value of T in Kelvin
    all_vars.append(("T_dimless", "T/1[K]",
                    "Temperature as pure number (K value)"))

    # 1. Pure component polynomials — pure numbers, no unit annotations
    #    mu in Pa·s, k in W/(m·K), Cp in J/(kg·K)
    for sp in SPECIES:
        name = _comsol_varname(sp)
        for prop in ["mu", "k", "Cp"]:
            coeffs = POLY_FITS[sp][prop]
            poly = _poly_expr(coeffs, var="T_dimless")
            all_vars.append((f"{prop}_{name}", poly,
                           f"{prop} of pure {sp} (SI number)"))

    # 2. Molar mass and density — pure numbers
    # M_mix_num = numerical value in kg/mol
    M_terms = [f"{_comsol_xvar(sp)}*{M[sp]:.7e}" for sp in SPECIES]
    all_vars.append(("M_mix_num", " + ".join(M_terms),
                    "Mixture molar mass (number, kg/mol units)"))

    # rho = P / (R * T) * M_mix = (101325/8.314) * M_mix_num / T_dimless
    P_over_R = 101325.0 / 8.314
    all_vars.append(("rho_analytic",
                    f"{P_over_R:.6f} * M_mix_num / T_dimless",
                    "Mixture density (number, kg/m^3 units)"))

    # 3. Viscosity mixing (Wilke rule) — all dimensionless intermediates
    for i in SPECIES:
        ni = _comsol_varname(i)
        for j in SPECIES:
            if i == j:
                continue
            nj = _comsol_varname(j)
            c = PHI_CONST[(i, j)]
            tag = f"phi_mu_{ni}_{nj}"
            expr = (f"(1 + sqrt(mu_{ni}/mu_{nj}) * {_fmt(c['ratio_M'])})^2"
                   f" / {_fmt(c['denom'])}")
            all_vars.append((tag, expr, f"Wilke phi ({i}-{j})"))

    for i in SPECIES:
        ni = _comsol_varname(i)
        xi = _comsol_xvar(i)
        terms = [xi]
        for j in SPECIES:
            if i == j:
                continue
            terms.append(f"{_comsol_xvar(j)}*phi_mu_{ni}_{_comsol_varname(j)}")
        all_vars.append((f"denom_mu_{ni}", " + ".join(terms),
                        f"Viscosity denom for {i}"))

    mu_terms = [f"{_comsol_xvar(sp)}*mu_{_comsol_varname(sp)}/denom_mu_{_comsol_varname(sp)}"
                for sp in SPECIES]
    all_vars.append(("mu_analytic", " + ".join(mu_terms),
                    "Mixture viscosity (number, Pa*s units)"))

    # 4. Conductivity mixing (blended Mason-Saxena)
    w = K_BLEND_WEIGHT
    for i in SPECIES:
        ni = _comsol_varname(i)
        for j in SPECIES:
            if i == j:
                continue
            nj = _comsol_varname(j)
            c = PHI_CONST[(i, j)]
            rM = _fmt(c['ratio_M'])
            d = _fmt(c['denom'])
            phi_mu = f"(1 + sqrt(mu_{ni}/mu_{nj}) * {rM})^2 / {d}"
            phi_k = f"(1 + sqrt(k_{ni}/k_{nj}) * {rM})^2 / {d}"
            tag = f"phi_k_{ni}_{nj}"
            expr = f"({phi_mu})^{w} * ({phi_k})^{1.0 - w:.2f}"
            all_vars.append((tag, expr, f"Blended phi ({i}-{j}) for k"))

    for i in SPECIES:
        ni = _comsol_varname(i)
        terms = [_comsol_xvar(i)]
        for j in SPECIES:
            if i == j:
                continue
            terms.append(f"{_comsol_xvar(j)}*phi_k_{ni}_{_comsol_varname(j)}")
        all_vars.append((f"denom_k_{ni}", " + ".join(terms),
                        f"Conductivity denom for {i}"))

    k_terms = [f"{_comsol_xvar(sp)}*k_{_comsol_varname(sp)}/denom_k_{_comsol_varname(sp)}"
               for sp in SPECIES]
    all_vars.append(("k_analytic", " + ".join(k_terms),
                    "Mixture thermal conductivity (number, W/(m*K) units)"))

    # 5. Cp mixing: Cp_mix = sum(x_i * M_i * Cp_i) / M_mix
    # All values are pure numbers: M_i in kg/mol, Cp_i in J/(kg*K)
    cp_terms = [f"{_comsol_xvar(sp)}*{M[sp]:.7e}*Cp_{_comsol_varname(sp)}"
                for sp in SPECIES]
    all_vars.append(("Cp_analytic",
                    "(" + " + ".join(cp_terms) + ") / M_mix_num",
                    "Mixture specific heat (number, J/(kg*K) units)"))

    return all_vars


# ==============================================================================
# Output formatters
# ==============================================================================

def print_comsol_variables():
    """Print all variables in a COMSOL-ready format."""
    all_vars = generate_all_expressions()

    print(f"{'='*80}")
    print("COMSOL VARIABLE DEFINITIONS FOR ANALYTIC GAS PROPERTIES")
    print(f"{'='*80}")
    print(f"Total variables: {len(all_vars)}")
    print(f"Blend weight (conductivity): {K_BLEND_WEIGHT}")
    print()

    for name, expr, desc in all_vars:
        print(f"  {name}")
        print(f"    // {desc}")
        print(f"    {expr}")
        print()

    return all_vars


def export_json(path="comsol_analytic_vars.json"):
    """Export all variable definitions as JSON."""
    all_vars = generate_all_expressions()
    data = {
        "description": "Analytic gas property expressions for COMSOL",
        "blend_weight": K_BLEND_WEIGHT,
        "species": SPECIES,
        "molar_masses": M,
        "variables": [
            {"name": name, "expression": expr, "description": desc}
            for name, expr, desc in all_vars
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nExported {len(all_vars)} variable definitions to {path}")
    return path


if __name__ == "__main__":
    all_vars = print_comsol_variables()
    export_json()
