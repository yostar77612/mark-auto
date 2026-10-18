# ChatGPT desktop dependency notices

`chatgpt-auth-native-notices.zip` is a standard, unextracted archive of 93 reviewed license, notice, SBOM and provenance files plus its manifest. Open it with an ordinary ZIP viewer to read the notices. The desktop bundle retains it under `_internal/licenses/`.

Archive SHA256:
`cbf2c6123cd25e53b33e766fb27bea9c9b4d8d174deb5ae54519d07f62dc9b24`

Pinned runtime distributions: PyJWT 2.15.1, cryptography 50.0.2, cffi 2.1.1 and pycparser 3.11. The archive includes native OpenSSL 4.0.3, the exact declared Rust dependencies, cffi's vendored libffi attribution, and separately labeled build-only/excluded components. Complete exact-wheel SBOMs and source-to-notice records are included.

Twenty-eight registry/native source archives were SHA256-verified. Notice texts for five other components were independently retrieved from their official exact-version upstream tags/commits and checked against Git blob identities and sizes: syn 2.0.119, unicode-ident 1.0.24, OpenSSL 4.0.3, target-lexicon 0.13.5 and vcpkg 0.2.15. Their original archive fetches were unavailable; the archive provenance retains that distinction. This is notice provenance, not a source-to-binary reproducible-build or legal-compliance guarantee.

The collector checks this exact ZIP hash and the four runtime versions and copies the verified bytes without extracting entries. Any dependency or notice change requires a fresh component review and an updated code pin. Do not regenerate or edit this archive silently.

Primary release references:
- https://pypi.org/project/PyJWT/2.15.1/
- https://pypi.org/project/cryptography/50.0.2/
- https://pypi.org/project/cffi/2.1.1/
- https://pypi.org/project/pycparser/3.11/

Each component's exact source URL, version, license expression, scope and available checksum/commit evidence are inside the archive's provenance and SBOM files.
