# Signing readiness checklist

**NOTHING is signed today.** Application and installer remain unsigned. This is
a future checklist, not execution evidence. Do not bypass SmartScreen or claim
that SHA-256 proves publisher identity.

- Acquire a public code-signing certificate from a trusted CA, complete identity
  validation, arrange protected key storage/signing service, and record renewal
  and revocation responsibilities. Check provider requirements before purchase.
- Pin the Windows SDK SignTool and exact authorized certificate thumbprint;
  verify publisher, validity and code-signing usage. Obtain the CA's RFC3161 URL.
- Sign the frozen application **before** generating the payload inventory;
  signing changes bytes. Compile Setup from that inventory, then sign Setup.
  Templates (placeholders must be replaced):

  ```powershell
  signtool sign /sha1 <CERT_THUMBPRINT> /fd SHA256 /tr <RFC3161_URL> /td SHA256 dist/MarkAuto/MarkAuto.exe
  signtool sign /sha1 <CERT_THUMBPRINT> /fd SHA256 /tr <RFC3161_URL> /td SHA256 dist/installers/<installer>.exe
  signtool verify /pa /all /v dist/MarkAuto/MarkAuto.exe
  signtool verify /pa /all /v dist/installers/<installer>.exe
  Get-AuthenticodeSignature -LiteralPath dist/MarkAuto/MarkAuto.exe | Format-List Status,SignerCertificate,TimeStamperCertificate
  Get-AuthenticodeSignature -LiteralPath dist/installers/<installer>.exe | Format-List Status,SignerCertificate,TimeStamperCertificate
  ```

- Require successful verification and `Valid` status for both final artifacts;
  independently match expected publisher/thumbprint and inspect timestamps.
  Archive verification logs, recompute final hashes, and rerun disposable Windows
  installer lifecycle/upgrade tests after signing.
- CI secrets: use approved protected release environments, narrowly scoped
  signing access and preferably non-exportable keys. Never put keys, PFX
  passwords, PINs or access tokens in source, logs or artifacts. Remove temporary
  credentials; rotate/revoke compromised access.
- When ready, change `build.ps1` to enforce application signing and verification
  before `payload_inventory.py`. Configure Inno's `SignTool` command in
  `markauto.iss` and ISCC invocation for Setup; use `SignedUninstaller=yes` if
  shipping a signed uninstaller. Verify final Setup after compilation and avoid
  double signing. Extend build-manifest evidence and acceptance tests together.
  None of these build/installer changes is enabled by T15.

References: [Microsoft SignTool](https://learn.microsoft.com/windows/win32/seccrypto/signtool),
[Get-AuthenticodeSignature](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature).
Inno configuration: [SignTool](https://jrsoftware.org/ishelp/topic_setup_signtool.htm),
[SignedUninstaller](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm).
