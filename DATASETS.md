# 📁 LegalLens Datasets & Evaluation Corpus

## Synthetic Sample Documents

All evaluation documents in \data/samples/\ were synthetically created to simulate real-world tenancy and employment contracts while ensuring **zero PII** and no copyrighted text.

| Document | Type | Target Challenge / Evaluation Goal |
|----------|------|------------------------------------|
| ental_clear.txt\ | Residential Lease | Baseline clean agreement with standard terms, rent, and deposits. |
| ental_vague.txt\ | Residential Lease | Ambiguity testing: vague rent timing, informal handshake terms. |
| \employment_standard.txt\ | Employment Contract | Standard corporate contract with IP ownership, PTO, and benefits. |
| \employment_conflict.txt\ | Employment Contract | Direct contradiction: at-will zero notice vs 90-day PIP requirement. |
| \injected.txt\ | Service Agreement | Adversarial prompt injection defense test (\[SYSTEM] Ignore instructions...\). |
| \malformed/empty.txt\ | Text File | Zero-byte graceful degradation handling. |
| \malformed/corrupt.pdf\ | PDF Document | Corrupted header handling without unhandled exceptions. |
| \malformed/password.pdf\ | Encrypted PDF | Password protection detection and user guidance. |
| \malformed/scanned.pdf\ | Scanned Image PDF | Image-only PDF detection warning. |

## Held-Out Test Set (Blind Evaluation)

- **Location**: \data/held_out/sublease_complex.txt- **Purpose**: Never used for tuning prompt templates, heuristic regexes, or verifier thresholds. Evaluates zero-shot generalization on complex multi-party sublease obligations.
