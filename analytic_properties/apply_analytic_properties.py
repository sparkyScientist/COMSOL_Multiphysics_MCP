#!/usr/bin/env python3.11
"""Apply analytic gas property expressions to the COMSOL model.

Creates a Variables node with 49 analytic property definitions and overrides
the physics nodes (spf.fp1, ht.fluid1) to use them instead of the Material
Switch / Thermodynamics package.

Usage:
    python3.11 apply_analytic_properties.py              # Apply analytic properties
    python3.11 apply_analytic_properties.py --restore     # Restore to from_mat
    python3.11 apply_analytic_properties.py --check       # Check current settings
    python3.11 apply_analytic_properties.py --port 2036   # Specify mphserver port
"""

import argparse
import json
import sys
import mph

from generate_comsol_expressions import generate_all_expressions

# Units for each variable type
VARIABLE_UNITS = {
    "mu_He": "Pa*s", "mu_H2": "Pa*s", "mu_CH4": "Pa*s", "mu_N2": "Pa*s",
    "k_He": "W/(m*K)", "k_H2": "W/(m*K)", "k_CH4": "W/(m*K)", "k_N2": "W/(m*K)",
    "Cp_He": "J/(kg*K)", "Cp_H2": "J/(kg*K)", "Cp_CH4": "J/(kg*K)", "Cp_N2": "J/(kg*K)",
    "M_mix": "",  # unit annotation is in the expression
    "rho_analytic": "",  # dimensions from expression
    "mu_analytic": "Pa*s",
    "k_analytic": "W/(m*K)",
    "Cp_analytic": "J/(kg*K)",
}

VARIABLES_TAG = "var_analytic"
VARIABLES_LABEL = "Analytic Gas Properties"


def connect(port=2036):
    """Connect to mphserver and return (client, model, java_model)."""
    client = mph.Client(port=port)
    names = client.names()
    if not names:
        raise RuntimeError("No models loaded on mphserver")
    model = client.models()[0]
    print(f"Connected to model: {names[0][:60]}...")
    return client, model, model.java


def create_variables_node(jm):
    """Create a Variables node under comp1 with all analytic property expressions.

    If the node already exists, it will be cleared and re-populated.
    """
    comp = jm.component("comp1")

    # Check if variables node exists
    existing_tags = list(comp.variable().tags())
    if VARIABLES_TAG in [str(t) for t in existing_tags]:
        print(f"  Variables node '{VARIABLES_TAG}' exists, clearing...")
        comp.variable().remove(VARIABLES_TAG)

    # Create new variables node
    comp.variable().create(VARIABLES_TAG)
    var_node = comp.variable(VARIABLES_TAG)
    var_node.label(VARIABLES_LABEL)

    # Generate and add all expressions
    all_vars = generate_all_expressions()
    print(f"  Adding {len(all_vars)} variable definitions...")

    for i, (name, expr, desc) in enumerate(all_vars):
        var_node.set(name, expr)
        # Set description
        var_node.descr(name, desc)

    print(f"  Created Variables node '{VARIABLES_TAG}' with {len(all_vars)} variables")
    return len(all_vars)


def override_physics(jm):
    """Override spf.fp1 and ht.fluid1 to use analytic property variables.

    Sets material properties from 'from_mat' to 'userdef' and points to
    our analytic variable names.
    """
    print("\n  Overriding physics material properties...")

    # --- spf (Turbulent Flow) ---
    spf = jm.component("comp1").physics("spf")
    fp1 = spf.feature("fp1")

    # Density
    fp1.set("rho_mat", "userdef")
    fp1.set("rho", "rho_analytic")
    print("    spf.fp1: rho = rho_analytic")

    # Dynamic viscosity
    fp1.set("mu_mat", "userdef")
    fp1.set("mu", "mu_analytic")
    print("    spf.fp1: mu = mu_analytic")

    # --- ht (Heat Transfer in Fluids) ---
    ht = jm.component("comp1").physics("ht")
    fluid1 = ht.feature("fluid1")

    # Density
    fluid1.set("rho_mat", "userdef")
    fluid1.set("rho", "rho_analytic")
    print("    ht.fluid1: rho = rho_analytic")

    # Thermal conductivity
    fluid1.set("k_mat", "userdef")
    fluid1.set("k", ["k_analytic", "0", "0", "0", "k_analytic", "0", "0", "0", "k_analytic"])
    print("    ht.fluid1: k = k_analytic (isotropic)")

    # Heat capacity
    fluid1.set("Cp_mat", "userdef")
    fluid1.set("Cp", "Cp_analytic")
    print("    ht.fluid1: Cp = Cp_analytic")

    # Dynamic viscosity (needed for convective terms in NonIsothermalFlow)
    fluid1.set("mu_mat", "userdef")
    fluid1.set("mu", "mu_analytic")
    print("    ht.fluid1: mu = mu_analytic")

    print("  Physics override complete.")


def restore_physics(jm):
    """Restore physics to use material properties (from_mat)."""
    print("\n  Restoring physics to from_mat...")

    # --- spf ---
    spf = jm.component("comp1").physics("spf")
    fp1 = spf.feature("fp1")
    fp1.set("rho_mat", "from_mat")
    fp1.set("mu_mat", "from_mat")
    print("    spf.fp1: rho, mu → from_mat")

    # --- ht ---
    ht = jm.component("comp1").physics("ht")
    fluid1 = ht.feature("fluid1")
    fluid1.set("rho_mat", "from_mat")
    fluid1.set("k_mat", "from_mat")
    fluid1.set("Cp_mat", "from_mat")
    fluid1.set("mu_mat", "from_mat")
    print("    ht.fluid1: rho, k, Cp, mu → from_mat")

    # Optionally remove the variables node
    existing_tags = [str(t) for t in jm.component("comp1").variable().tags()]
    if VARIABLES_TAG in existing_tags:
        jm.component("comp1").variable().remove(VARIABLES_TAG)
        print(f"    Removed Variables node '{VARIABLES_TAG}'")

    print("  Restore complete.")


def check_settings(jm):
    """Print current material property settings for spf and ht."""
    print("\n  Current physics material property settings:")

    # spf
    spf = jm.component("comp1").physics("spf")
    fp1 = spf.feature("fp1")
    for prop in ["rho_mat", "mu_mat"]:
        try:
            val = str(fp1.getString(prop))
            print(f"    spf.fp1.{prop} = {val}")
        except:
            print(f"    spf.fp1.{prop} = (error reading)")

    for prop in ["rho", "mu"]:
        try:
            val = str(fp1.getString(prop))
            print(f"    spf.fp1.{prop} = {val}")
        except:
            pass

    # ht
    ht = jm.component("comp1").physics("ht")
    fluid1 = ht.feature("fluid1")
    for prop in ["rho_mat", "k_mat", "Cp_mat", "mu_mat"]:
        try:
            val = str(fluid1.getString(prop))
            print(f"    ht.fluid1.{prop} = {val}")
        except:
            print(f"    ht.fluid1.{prop} = (error reading)")

    # Check variables node
    existing_tags = [str(t) for t in jm.component("comp1").variable().tags()]
    if VARIABLES_TAG in existing_tags:
        print(f"    Variables node '{VARIABLES_TAG}': present")
    else:
        print(f"    Variables node '{VARIABLES_TAG}': not present")


def apply(port=2036):
    """Apply analytic gas properties to the model."""
    client, model, jm = connect(port)

    try:
        print("\nStep 1: Creating Variables node...")
        n_vars = create_variables_node(jm)

        print("\nStep 2: Overriding physics to use analytic properties...")
        override_physics(jm)

        print("\nStep 3: Verifying settings...")
        check_settings(jm)

        print(f"\nDone. {n_vars} analytic property variables applied.")
        print("The model now uses analytic expressions for gas properties.")
        print("Global parameters (x_he, x_h2, x_ch4, x_n2) control the composition.")
        print("\nTo run a study: solve std8 (Stationary) in COMSOL.")
        print("To restore: python3.11 apply_analytic_properties.py --restore")

    finally:
        client.disconnect()


def restore(port=2036):
    """Restore model to use material switch."""
    client, model, jm = connect(port)
    try:
        restore_physics(jm)
        check_settings(jm)
        print("\nModel restored to Material Switch (from_mat).")
    finally:
        client.disconnect()


def check(port=2036):
    """Check current settings."""
    client, model, jm = connect(port)
    try:
        check_settings(jm)
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description="Apply/restore analytic gas properties in COMSOL model")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--restore", action="store_true",
                       help="Restore to material switch (from_mat)")
    group.add_argument("--check", action="store_true",
                       help="Check current material property settings")
    parser.add_argument("--port", type=int, default=2036,  # default COMSOL mphserver port; override with --port or COMSOL_PORT env var
                        help="mphserver port (default: 2036)")
    args = parser.parse_args()

    if args.restore:
        restore(args.port)
    elif args.check:
        check(args.port)
    else:
        apply(args.port)


if __name__ == "__main__":
    main()
