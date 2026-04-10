# Git Setup and Release Commands

Run these commands in order from the `COMSOL_MCP_release/` directory.

## 1. Initialize Repository

```bash
cd "/path/to/COMSOL_MCP_release"
git init
git remote add origin git@github.com:sparkyScientist/COMSOL_Multiphysics_MCP.git
```

## 2. Initial Commit

```bash
git add -A
git commit -m "Initial release: COMSOL Multiphysics MCP Server v0.1.0

Physics-aware MCP tooling for COMSOL via Java API.
Built on wjc9011/COMSOL_Multiphysics_MCP (MIT License).

Novel contributions:
- Physics-aware mesh builder with boundary detection
- Analytic gas property bypass (51 COMSOL variable expressions)
- Segregated solver setup with physics-aware step grouping
- Workflow memory for solver configuration reuse
- Automated 2D-to-3D geometry converter
- Validator and autofixer for post-conversion model repair
- ARES-Sim bridge for Bayesian optimization integration"
```

## 3. Tag the Release

```bash
git tag -a v0.1.0 -m "v0.1.0: Initial public release"
```

## 4. Push to GitHub

```bash
git branch -M main
git push -u origin main
git push origin v0.1.0
```

## 5. Zenodo Webhook Setup

1. Go to https://zenodo.org and log in (or create an account)
2. Navigate to Settings > GitHub
3. Click "Connect" to authorize Zenodo with your GitHub account
4. Find `sparkyScientist/COMSOL_Multiphysics_MCP` in the repository list
5. Toggle the switch to ON to enable automatic DOI assignment
6. Go back to GitHub and create a new release:
   - Go to https://github.com/sparkyScientist/COMSOL_Multiphysics_MCP/releases
   - Click "Create a new release"
   - Choose tag: `v0.1.0`
   - Title: `v0.1.0: COMSOL Multiphysics MCP Server`
   - Description: paste contents of ZENODO_DESCRIPTION.txt
   - Click "Publish release"
7. Zenodo will automatically archive the release and assign a DOI
8. The DOI badge will appear at https://zenodo.org/account/settings/github/

## 6. Update README Badge with DOI

Once the DOI is assigned (e.g., `10.5281/zenodo.XXXXXXX`), update README.md:

```bash
# Replace the placeholder DOI badge
sed -i '' 's|https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg|https://zenodo.org/badge/DOI/YOUR_ACTUAL_DOI.svg|g' README.md
sed -i '' 's|https://doi.org/10.5281/zenodo.XXXXXXX|https://doi.org/YOUR_ACTUAL_DOI|g' README.md

git add README.md CITATION.cff
git commit -m "Update DOI badge and citation with Zenodo DOI"
git push origin main
```

Also update the `doi` field in CITATION.cff with the assigned DOI.

## 7. Post-Release Checklist

- [ ] Verify README renders correctly on GitHub
- [ ] Verify Zenodo deposit includes all files
- [ ] Update DOI in README.md and CITATION.cff
- [ ] Consider JOSS submission (https://joss.theoj.org) for peer review
- [ ] Share on relevant channels (Twitter/X, LinkedIn, COMSOL forum)
