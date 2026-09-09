# Data

`raw/` is for externally sourced files such as the original Tox21 archive. `processed/` is for validated, canonicalized, and split tables. `evidence/` will hold generated frozen packet artifacts and provenance metadata.

Bulk data and evidence payloads are ignored by Git. Keep only placeholders, small provenance records, checksums, and documentation under version control. Never commit provider credentials, restricted documents, or data whose license forbids redistribution. Generated artifacts must retain enough metadata to trace them to their external source and transformation configuration.
