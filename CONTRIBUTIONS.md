# 👥 Team Contributions

## Person A — Verification & Safety
- Designed core verification engine ensuring findings quote exact source passages.
- Implemented output filters, contradiction detection, and jurisdictional warnings.

## Person B — Ingestion & Chunking
- Built multi-page PDF and TXT ingestion pipeline using \pypdf\.
- Implemented clause-aware boundary detection and paragraph segmentation.

## Person C — Local LLM Integration
- Built stdlib-only HTTP client interfacing local \llama-server\ (Gemma).
- Implemented robust JSON schema extraction, structured retry loops, and health checks.

## Person D — UI, Tests, Documentation & Demo
- Built Gradio-based web interface running strictly on W.0.0.1\ without CDN dependencies.
- Authored automated evaluation harness (\ench/run.py\, \ench/citation_accuracy.py\, \ench/speed_memory.py\, \ench/verifier.py\).
- Created synthetic test corpus (\data/samples/\) and blind held-out dataset (\data/held_out/\).
- Developed deterministic UI and schema tests (\	ests/test_ui.py\) and GitHub Actions CI workflow (\.github/workflows/ci.yml\).
- Produced documentation (\ARCHITECTURE.md\, \DATASETS.md\, \CONTRIBUTIONS.md\) and video demo recording.
