#!/usr/bin/env python3.11
"""Analytic gas mixture properties for He/N₂/H₂/CH₄ mixtures.

Replaces COMSOL's Thermodynamics package with:
  - Density: ideal gas law (exact)
  - Viscosity: polynomial pure-component fits + Wilke mixing
  - Thermal conductivity: polynomial pure-component fits + Mason-Saxena mixing
  - Heat capacity: polynomial pure-component fits + mole-weighted mixing

All polynomial fits are calibrated to COMSOL's thermodynamics data (300-1500K).
"""

import math
import numpy as np

# =============================================================================
# Constants
# =============================================================================
R_GAS = 8.314       # J/(mol·K)
P_ATM = 101325.0    # Pa (1 atm)

SPECIES = ["He", "H2", "CH4", "N2"]

# Molar masses [kg/mol]
M = {"He": 0.0040026, "H2": 0.0020159, "CH4": 0.016043, "N2": 0.028014}

# =============================================================================
# COMSOL pure-component reference data (from Densitypp1, Viscositypp1, etc.)
# Evaluated at 1 atm for pure species, T = 300..1500 K
# =============================================================================
COMSOL_PURE = {
    "He": {
        "T":  [300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500],
        "mu": [1.993168e-05, 2.430516e-05, 2.836845e-05, 3.221633e-05, 3.590993e-05,
               3.946514e-05, 4.289470e-05, 4.621134e-05, 4.942781e-05, 5.255683e-05,
               5.561115e-05, 5.860350e-05, 6.154661e-05],
        "k":  [0.155773, 0.190246, 0.222388, 0.252565, 0.281140, 0.308478, 0.334902,
               0.360538, 0.385446, 0.409687, 0.433323, 0.456415, 0.479024],
        "Cp": [5193.17]*13,
    },
    "H2": {
        "T":  [300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500],
        "mu": [8.934701e-06, 1.090752e-05, 1.274155e-05, 1.446972e-05, 1.611774e-05,
               1.770693e-05, 1.924438e-05, 2.073435e-05, 2.218107e-05, 2.358879e-05,
               2.496177e-05, 2.630423e-05, 2.762044e-05],
        "k":  [0.186871, 0.231497, 0.271077, 0.308964, 0.346378, 0.383987, 0.422171,
               0.460955, 0.500342, 0.540336, 0.580940, 0.622158, 0.663993],
        "Cp": [14314.66, 14478.39, 14512.95, 14551.12, 14613.55, 14710.38, 14839.84,
               14996.96, 15176.79, 15374.35, 15584.70, 15802.86, 16023.88],
    },
    "CH4": {
        "T":  [300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500],
        "mu": [1.114390e-05, 1.416945e-05, 1.690013e-05, 1.939960e-05, 2.170793e-05,
               2.386522e-05, 2.591104e-05, 2.787141e-05, 2.975805e-05, 3.158197e-05,
               3.335415e-05, 3.508563e-05, 3.678739e-05],
        "k":  [0.034353, 0.049827, 0.068284, 0.088806, 0.110536, 0.133066, 0.156048,
               0.179110, 0.202171, 0.225234, 0.248296, 0.271359, 0.294422],
        "Cp": [2231.77, 2531.06, 2898.13, 3272.13, 3627.82, 3958.32, 4261.75,
               4537.91, 4786.65, 5009.25, 5208.31, 5386.49, 5546.45],
    },
    "N2": {
        "T":  [300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500],
        "mu": [1.789225e-05, 2.220842e-05, 2.606221e-05, 2.958419e-05, 3.285005e-05,
               3.590299e-05, 3.878578e-05, 4.154068e-05, 4.419608e-05, 4.676459e-05,
               4.925796e-05, 5.168793e-05, 5.406625e-05],
        "k":  [0.026016, 0.032847, 0.039075, 0.044871, 0.050329, 0.055535, 0.060553,
               0.065408, 0.070124, 0.074722, 0.079223, 0.083650, 0.088025],
        "Cp": [1040.32, 1045.02, 1055.93, 1074.61, 1097.89, 1122.15, 1145.63,
               1167.10, 1186.37, 1203.57, 1218.80, 1232.21, 1243.90],
    },
}

# =============================================================================
# Polynomial fitting: fit each pure-component property as polynomial in T
# =============================================================================

def _fit_polynomial(T_data, y_data, degree=4):
    """Fit a polynomial y = c0 + c1*T + c2*T^2 + ... to data."""
    coeffs = np.polyfit(T_data, y_data, degree)
    return coeffs[::-1]  # return as [c0, c1, c2, ...] (low to high)


def _eval_polynomial(T, coeffs):
    """Evaluate polynomial c0 + c1*T + c2*T^2 + ..."""
    result = 0.0
    for i, c in enumerate(coeffs):
        result += c * T**i
    return result


# Fit all pure component properties
POLY_FITS = {}
for sp in SPECIES:
    T_data = np.array(COMSOL_PURE[sp]["T"], dtype=float)
    POLY_FITS[sp] = {}
    for prop in ["mu", "k", "Cp"]:
        y_data = np.array(COMSOL_PURE[sp][prop], dtype=float)
        POLY_FITS[sp][prop] = _fit_polynomial(T_data, y_data, degree=4)


# =============================================================================
# Property functions
# =============================================================================

def molar_mass_mix(x_he, x_h2, x_ch4, x_n2):
    """Mixture molar mass [kg/mol]."""
    return x_he * M["He"] + x_h2 * M["H2"] + x_ch4 * M["CH4"] + x_n2 * M["N2"]


def rho_mix(T, x_he, x_h2, x_ch4, x_n2):
    """Mixture density [kg/m³] from ideal gas law."""
    M_mix = molar_mass_mix(x_he, x_h2, x_ch4, x_n2)
    return P_ATM * M_mix / (R_GAS * T)


def _mu_pure(T):
    """Pure component viscosities [Pa·s] from polynomial fits."""
    return {sp: _eval_polynomial(T, POLY_FITS[sp]["mu"]) for sp in SPECIES}


def _k_pure(T):
    """Pure component thermal conductivities [W/(m·K)] from polynomial fits."""
    return {sp: _eval_polynomial(T, POLY_FITS[sp]["k"]) for sp in SPECIES}


def _Cp_pure_mass(T):
    """Pure component mass-specific Cp [J/(kg·K)] from polynomial fits."""
    return {sp: _eval_polynomial(T, POLY_FITS[sp]["Cp"]) for sp in SPECIES}


def _wilke_phi(mu_i, mu_j, Mi, Mj):
    """Wilke interaction parameter phi_ij."""
    ratio_mu = math.sqrt(mu_i / mu_j)
    ratio_M = (Mj / Mi) ** 0.25
    return (1.0 + ratio_mu * ratio_M) ** 2 / math.sqrt(8.0 * (1.0 + Mi / Mj))


def mu_mix(T, x_he, x_h2, x_ch4, x_n2):
    """Mixture dynamic viscosity [Pa·s] via Wilke mixing rule."""
    x = {"He": x_he, "H2": x_h2, "CH4": x_ch4, "N2": x_n2}
    mu = _mu_pure(T)

    result = 0.0
    for i in SPECIES:
        if x[i] < 1e-15:
            continue
        denom = 0.0
        for j in SPECIES:
            if x[j] < 1e-15:
                continue
            if i == j:
                phi = 1.0
            else:
                phi = _wilke_phi(mu[i], mu[j], M[i], M[j])
            denom += x[j] * phi
        result += x[i] * mu[i] / denom
    return result


def _k_phi(mu_i, mu_j, k_i, k_j, Mi, Mj):
    """Blended phi_ij for conductivity mixing.

    Geometric mean of Wilke (mu-ratio) and Wassiljewa (k-ratio) phi_ij,
    weighted by K_BLEND_WEIGHT. Calibrated to match COMSOL thermodynamics data.
      w=1.0 → pure Wilke (overestimates for N₂-rich)
      w=0.0 → pure k-ratio (underestimates)
    """
    ratio_M = (Mj / Mi) ** 0.25
    denom = math.sqrt(8.0 * (1.0 + Mi / Mj))

    phi_mu = (1.0 + math.sqrt(mu_i / mu_j) * ratio_M) ** 2 / denom
    phi_k = (1.0 + math.sqrt(k_i / k_j) * ratio_M) ** 2 / denom

    w = K_BLEND_WEIGHT
    return phi_mu ** w * phi_k ** (1.0 - w)


# Calibrated blend weight (optimized against COMSOL mixture data, max k error = 2.41%)
K_BLEND_WEIGHT = 0.93


def k_mix(T, x_he, x_h2, x_ch4, x_n2):
    """Mixture thermal conductivity [W/(m·K)] via blended Mason-Saxena mixing."""
    x = {"He": x_he, "H2": x_h2, "CH4": x_ch4, "N2": x_n2}
    mu = _mu_pure(T)
    k = _k_pure(T)

    result = 0.0
    for i in SPECIES:
        if x[i] < 1e-15:
            continue
        denom = 0.0
        for j in SPECIES:
            if x[j] < 1e-15:
                continue
            if i == j:
                phi = 1.0
            else:
                phi = _k_phi(mu[i], mu[j], k[i], k[j], M[i], M[j])
            denom += x[j] * phi
        result += x[i] * k[i] / denom
    return result


def Cp_mix(T, x_he, x_h2, x_ch4, x_n2):
    """Mixture specific heat capacity [J/(kg·K)].

    Cp_mix = sum(x_i * M_i * Cp_i_mass) / M_mix
    = sum(x_i * Cp_i_molar) / M_mix

    where Cp_i_molar = Cp_i_mass * M_i
    """
    x = {"He": x_he, "H2": x_h2, "CH4": x_ch4, "N2": x_n2}
    cp_mass = _Cp_pure_mass(T)
    # Convert to molar: Cp_molar_i = Cp_mass_i * M_i
    cp_molar_mix = sum(x[sp] * cp_mass[sp] * M[sp] for sp in SPECIES)
    M_mix = molar_mass_mix(x_he, x_h2, x_ch4, x_n2)
    return cp_molar_mix / M_mix


# =============================================================================
# COMSOL mixture reference data for validation
# =============================================================================
COMSOL_MIX_DATA = {
    "pure_He": {
        "x": (0.61, 0.365, 0.025, 0.0),
        "T":   [300, 500, 700, 900, 1100, 1300, 1500],
        "rho": [0.145364, 0.087219, 0.062299, 0.048455, 0.039645, 0.033546, 0.029073],
        "mu":  [1.5438e-05, 2.2051e-05, 2.7927e-05, 3.3353e-05, 3.8430e-05, 4.3233e-05, 4.7836e-05],
        "k":   [0.16255, 0.23377, 0.29740, 0.35848, 0.41869, 0.47833, 0.53771],
        "Cp":  [6736.8, 6852.3, 6954.7, 7072.3, 7200.4, 7331.6, 7459.8],
    },
    "51He_10N2": {
        "x": (0.51, 0.365, 0.025, 0.10),
        "T":   [300, 500, 700, 900, 1100, 1300, 1500],
        "rho": [0.242899, 0.145739, 0.104100, 0.080966, 0.066245, 0.056054, 0.048580],
        "mu":  [1.6327e-05, 2.3429e-05, 2.9643e-05, 3.5315e-05, 4.0592e-05, 4.5572e-05, 5.0336e-05],
        "k":   [0.13745, 0.19742, 0.25059, 0.30151, 0.35170, 0.40151, 0.45118],
        "Cp":  [4171.4, 4247.8, 4328.8, 4421.6, 4517.3, 4611.0, 4699.5],
    },
    "30He_31N2": {
        "x": (0.30, 0.365, 0.025, 0.31),
        "T":   [300, 500, 700, 900, 1100, 1300, 1500],
        "rho": [0.447722, 0.268633, 0.191881, 0.149241, 0.122106, 0.103321, 0.089544],
        "mu":  [1.6949e-05, 2.4486e-05, 3.0936e-05, 3.6720e-05, 4.2059e-05, 4.7079e-05, 5.1866e-05],
        "k":   [0.09863, 0.14211, 0.18032, 0.21689, 0.25304, 0.28907, 0.32518],
        "Cp":  [2422.3, 2472.1, 2538.4, 2614.2, 2687.9, 2756.0, 2817.4],
    },
    "pure_N2": {
        "x": (0.0, 0.365, 0.025, 0.61),
        "T":   [300, 500, 700, 900, 1100, 1300, 1500],
        "rho": [0.740327, 0.444196, 0.317283, 0.246776, 0.201907, 0.170845, 0.148065],
        "mu":  [1.6790e-05, 2.4401e-05, 3.0789e-05, 3.6428e-05, 4.1593e-05, 4.6434e-05, 5.1038e-05],
        "k":   [0.06231, 0.09142, 0.11695, 0.14158, 0.16610, 0.19073, 0.21562],
        "Cp":  [1602.5, 1639.8, 1699.2, 1767.1, 1830.5, 1886.6, 1935.3],
    },
    "97.5H2": {
        "x": (0.0, 0.975, 0.025, 0.0),
        "T":   [300, 500, 700, 900, 1100, 1300, 1500],
        "rho": [0.096135, 0.057681, 0.041201, 0.032045, 0.026219, 0.022185, 0.019227],
        "mu":  [9.1892e-06, 1.3152e-05, 1.6653e-05, 1.9883e-05, 2.2912e-05, 2.5778e-05, 2.8518e-05],
        "k":   [0.17957, 0.26130, 0.33472, 0.40863, 0.48477, 0.56320, 0.64396],
        "Cp":  [12266.9, 12544.5, 12751.7, 13047.1, 13415.9, 13826.2, 14248.2],
    },
}


# =============================================================================
# Validation
# =============================================================================

def validate_all():
    """Compare analytic properties against COMSOL thermodynamics data."""
    props = [
        ("rho", "Density [kg/m³]", rho_mix),
        ("mu",  "Viscosity [Pa·s]", mu_mix),
        ("k",   "Conductivity [W/mK]", k_mix),
        ("Cp",  "Heat capacity [J/kgK]", Cp_mix),
    ]

    max_errors = {}

    for comp_name, data in COMSOL_MIX_DATA.items():
        x_he, x_h2, x_ch4, x_n2 = data["x"]
        print(f"\n{'='*80}")
        print(f"  {comp_name}  (He={x_he}, H2={x_h2}, CH4={x_ch4}, N2={x_n2})")
        print(f"{'='*80}")

        for prop_key, prop_label, prop_func in props:
            comsol_vals = data[prop_key]
            temps = data["T"]

            print(f"\n  {prop_label}:")
            print(f"  {'T(K)':>6s}  {'Analytic':>12s}  {'COMSOL':>12s}  {'Error%':>8s}")
            print(f"  {'-'*42}")

            errors = []
            for T, comsol_val in zip(temps, comsol_vals):
                analytic_val = prop_func(T, x_he, x_h2, x_ch4, x_n2)
                err_pct = (analytic_val - comsol_val) / comsol_val * 100.0
                errors.append(abs(err_pct))

                flag = " !!!" if abs(err_pct) > 5 else ""
                if prop_key == "mu":
                    print(f"  {T:6d}  {analytic_val:12.4e}  {comsol_val:12.4e}  {err_pct:+7.2f}%{flag}")
                elif prop_key == "k":
                    print(f"  {T:6d}  {analytic_val:12.5f}  {comsol_val:12.5f}  {err_pct:+7.2f}%{flag}")
                elif prop_key == "Cp":
                    print(f"  {T:6d}  {analytic_val:12.1f}  {comsol_val:12.1f}  {err_pct:+7.2f}%{flag}")
                else:
                    print(f"  {T:6d}  {analytic_val:12.6f}  {comsol_val:12.6f}  {err_pct:+7.2f}%{flag}")

            max_err = max(errors)
            if prop_key not in max_errors or max_err > max_errors[prop_key]:
                max_errors[prop_key] = max_err

            if max_err > 5:
                print(f"  >>> WARNING: max error {max_err:.1f}% exceeds 5% threshold")
            elif max_err > 2:
                print(f"  >>> Note: max error {max_err:.1f}% (acceptable)")
            else:
                print(f"  >>> OK: max error {max_err:.1f}%")

    print(f"\n{'='*80}")
    print("SUMMARY OF MAX ERRORS ACROSS ALL COMPOSITIONS")
    print(f"{'='*80}")
    all_ok = True
    for prop_key, max_err in max_errors.items():
        status = "OK" if max_err < 5 else "NEEDS WORK"
        if max_err >= 5:
            all_ok = False
        print(f"  {prop_key:5s}: max error = {max_err:.2f}%  [{status}]")

    return max_errors, all_ok


def print_polynomial_coefficients():
    """Print the fitted polynomial coefficients for documentation."""
    print(f"\n{'='*80}")
    print("POLYNOMIAL COEFFICIENTS (fitted to COMSOL pure-component data)")
    print("  p(T) = c0 + c1*T + c2*T^2 + c3*T^3 + c4*T^4")
    print(f"{'='*80}")
    for sp in SPECIES:
        print(f"\n  {sp}:")
        for prop in ["mu", "k", "Cp"]:
            coeffs = POLY_FITS[sp][prop]
            terms = [f"{coeffs[i]:.10e}*T^{i}" if i > 0 else f"{coeffs[0]:.10e}"
                     for i in range(len(coeffs))]
            print(f"    {prop:3s} = {' + '.join(terms)}")


def _optimize_k_blend():
    """Find optimal K_BLEND_WEIGHT to minimize max conductivity error."""
    global K_BLEND_WEIGHT

    best_w, best_max_err = 0.5, 1e9
    for w_int in range(0, 101):
        w = w_int / 100.0
        K_BLEND_WEIGHT = w
        max_err = 0.0
        for data in COMSOL_MIX_DATA.values():
            x_he, x_h2, x_ch4, x_n2 = data["x"]
            for T, k_ref in zip(data["T"], data["k"]):
                k_calc = k_mix(T, x_he, x_h2, x_ch4, x_n2)
                err = abs((k_calc - k_ref) / k_ref * 100.0)
                if err > max_err:
                    max_err = err
        if max_err < best_max_err:
            best_max_err = max_err
            best_w = w
    K_BLEND_WEIGHT = best_w
    return best_w, best_max_err


if __name__ == "__main__":
    # Optimize blend weight first
    print("Optimizing conductivity blend weight...")
    best_w, best_err = _optimize_k_blend()
    print(f"  Optimal K_BLEND_WEIGHT = {best_w:.2f}  (max k error = {best_err:.2f}%)")

    print_polynomial_coefficients()
    max_errors, all_ok = validate_all()

    if all_ok:
        print("\n*** All properties within 5% of COMSOL. Ready for COMSOL expressions. ***")
    else:
        print("\n*** Some properties exceed 5%. Review polynomial fits. ***")
