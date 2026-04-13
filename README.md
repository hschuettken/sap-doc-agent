# SAP Documentation Agent

Automated documentation, quality assurance, and code audit for SAP BW/4HANA and Datasphere.

See [SPEC.md](SPEC.md) for the full design specification.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml
# Edit config.yaml for your environment
pytest
```
