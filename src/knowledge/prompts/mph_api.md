# MPh API Reference

This document provides a quick reference for the MPh (Python-COMSOL interface) API.

## Installation

```bash
pip install mph
```

## Core Classes

### Client

The `Client` class manages the COMSOL session.

```python
import mph

# Start local session
client = mph.Client(cores=1, version='6.0')

# Connect to server
client = mph.Client(port=2036, host='localhost')

# Properties
client.version      # COMSOL version string
client.standalone   # True if standalone, False if connected
client.cores        # Number of cores in use
client.host         # Server host name
client.port         # Server port number
```

### Model

The `Model` class represents a COMSOL model.

```python
# Load model
model = client.load('capacitor.mph')

# Create new model
model = client.create('my_model')

# Model info
model.name()        # Model name
model.file()        # File path
model.version()     # COMSOL version when saved

# List features
model.parameters()  # Dict of parameters
model.physics()     # List of physics interfaces
model.geometries()  # List of geometry sequences
model.meshes()      # List of mesh sequences
model.studies()     # List of studies
model.datasets()    # List of datasets
model.plots()       # List of plots
model.exports()     # List of exports
model.materials()   # List of materials

# Operations
model.build()       # Build geometry
model.mesh()        # Generate mesh
model.solve()       # Solve study
model.save()        # Save model
model.clear()       # Clear solution data
model.reset()       # Reset history
```

### Parameters

```python
# Get/set parameter
value = model.parameter('U')           # Returns expression string
model.parameter('U', '5[V]')           # Set parameter value

# Get all parameters
params = model.parameters()            # Dict {name: expression}
params = model.parameters(evaluate=True)  # Dict {name: float}

# Description
desc = model.description('U')          # Get description
model.description('U', 'Applied voltage')  # Set description
descs = model.descriptions()           # Dict of all descriptions
```

### Evaluation

```python
# Evaluate expression
result = model.evaluate('es.normE', 'V/m')
result = model.evaluate(['x', 'y', 'T'], dataset='dset1')

# Global evaluation (scalar)
C = model.evaluate('2*es.intWe/U^2', 'pF')

# Time-dependent solutions
(indices, times) = model.inner('time-dependent')

# Parametric sweeps
(indices, values) = model.outer('parametric sweep')

# Selection
model.evaluate(expr, unit, dataset, inner='first')  # First time step
model.evaluate(expr, unit, dataset, inner='last')   # Last time step
model.evaluate(expr, unit, dataset, inner=[0, 5])   # Steps 0 and 5
model.evaluate(expr, unit, dataset, outer=1)        # Sweep index 1
```

### Node

Access model tree nodes:

```python
# Access by path
geom = model / 'geometries' / 'geometry1'
physics = model / 'physics' / 'electrostatic'

# Create features
block = geom.create('Block')
bc = physics.create('Ground')

# Properties
block.property('size', [1, 1, 1])
block.property('pos', [0, 0, 0])
value = block.property('size')

# Remove
model.remove(block)
```

### Export

```python
# Export via model
model.export('data', 'output.txt')
model.export('image', 'plot.png')

# Export all
model.export()
```

## Common Patterns

### Load, Modify, Solve

```python
import mph

client = mph.start()
model = client.load('capacitor.mph')

# Modify parameter
model.parameter('U', '10[V]')

# Solve
model.solve('static')

# Evaluate
C = model.evaluate('2*es.intWe/U^2', 'pF')
print(f'Capacitance: {C:.3f} pF')

# Save
model.save('capacitor_modified.mph')
```

### Create New Model

```python
model = client.create('new_model')

# Add geometry
geom = model / 'geometries' / 'geom1'
block = geom.create('Block')
block.property('size', ['L', 'W', 'H'])
geom.build()

# Add physics
es = model.create('physics', 'Electrostatics')

# Add study
study = model / 'studies' / 'study1'
stationary = study.create('Stationary')

# Mesh and solve
model.mesh()
model.solve()
```

## Error Handling

```python
try:
    model = client.load('nonexistent.mph')
except Exception as e:
    print(f'Error: {e}')
```

## Limitations

- Only one Client instance per Python process
- COMSOL must be installed and licensed
- Java (JPype) bridge required
- Some advanced features require direct Java API access
