# Handle registry propagation in release verification

Release publishing succeeded for 0.148.1, 0.149.0 and 0.150.0, but immediate registry reads temporarily reported older versions or missing index entries. Make release verification tolerate a short bounded propagation interval and accurately report publication versus index visibility. Preserve exact-version artifact checks, avoid republishing or retagging, and keep the existing overall timeout. Batch this polish with the next release.
