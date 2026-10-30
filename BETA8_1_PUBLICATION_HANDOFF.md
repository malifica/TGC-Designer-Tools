# Beta 8.1 publication handoff

## Published release

[Beta 8.1 Windows prerelease](https://github.com/malifica/TGC-Designer-Tools/releases/tag/v0.5.0-2k25-beta8.1) uses the supplied `tgc_gui_2k25_beta8_1.exe` unchanged. Its release tag points to source commit [`67980485fd0639e3458382487ed1fee831de078d`](https://github.com/malifica/TGC-Designer-Tools/commit/67980485fd0639e3458382487ed1fee831de078d).

The executable is 194,211,815 bytes with SHA-256 `d05d4e17e59a4e69d7185d411341cef9b3c713ad6e6fc4e48101c63aec9f37d4`. See `BETA8_1_BUILD_SOURCE_MANIFEST.json`, `BETA8_1_BUILD_VALIDATION.json`, and `BETA8_1_UPLOAD_MANIFEST.json` for the recorded source and binary checks. No additional Windows GUI or in-game testing is claimed.

The [publication workflow](https://github.com/malifica/TGC-Designer-Tools/actions/runs/41085429145) downloaded all four public assets and both automatic source archives without authentication. Their bytes, checksums, packaged support, and all 187 committed source files passed verification. The complete result is recorded in [BETA8_1_PUBLICATION_VERIFICATION.json](BETA8_1_PUBLICATION_VERIFICATION.json).

The procedure below is retained as publication history and guardrails. The existing public tag and assets must not be replaced with different bytes.

## Source preparation

Repository: `malifica/TGC-Designer-Tools`. Source preparation started from Beta 8 commit `670e7aa57a19d6a6228718e40c6b846e34e72034` and produced commit `4d666d4c91b877bb755d8e3f29104b24e4dc89d9`. Publication then recorded the actual build and matching source in the release commit above. The publication-control branch is `release/beta8.1-publication`; do not rerun its source-preparation workflow after main has advanced.

Identity:
- Tag: `v0.5.0-2k25-beta8.1`
- Title: `TGC Designer Tools 2K25 - Beta 8.1`
- EXE: `tgc_gui_2k25_beta8_1.exe`
- Windows ZIP: `TGC-Designer-Tools-2K25-v0.5.0-2k25-beta8.1-Windows-x64.zip`
- Release notes: `RELEASE_NOTES_v0.5.0-2k25-beta8.1.md`
- Build: `BUILD_TGC_2K25_BETA8_1.py` / `.bat`
- Frozen entry point remains `tgc_beta8_entry.py`, with every existing dispatch route retained.

## Follow the Beta 8 method

The prior successful publication used branch `release/beta8-publication`; the final verification workflow is `.github/workflows/finalize-existing-beta8.yml`, run `41047035063`. Study its history for the earlier source/asset transfer stages. It uploaded existing EXE bytes and a Windows ZIP, two SHA-256 sidecars, and verified anonymous public downloads. It did not rebuild during publication. Node 24 was required; retain `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` and Node-24-compatible action versions.

Do not reuse Beta 8 release IDs, asset IDs, hashes, or target commit. The old release and tag must remain unchanged.

## Supplied input

The supplied archive was `TGC_BETA8_1_EXISTING_BUILD_AND_SOURCE_20261030T142434_679432Z.zip`. It contains `dist/tgc_gui_2k25_beta8_1.exe`, matching application source, profiles/build support, and `UPLOAD_MANIFEST.json`. All 142 manifest entries were verified. No Beta 8.1 EXE was created by source preparation.

The build and collector commands remain documented in BUILD_WINDOWS.md for development. The published executable was supplied separately and was not rebuilt during publication.

## Publication procedure (reference)

1. Verify every upload-manifest entry and record the supplied EXE SHA-256. Check its PE header, embedded release identity, required standard-OSM code and independent woodland/tree options. Compare matching Python source against frozen modules using the same Python bytecode version; do not compare Python 3.11 and 3.13 marshalled code naively. Include packaged regional profiles and supporting assets.
2. Reconcile the actual build's source with current main. Do not overwrite newer source, drop unrelated updates, or label a mismatched tree as matching. BETA8_1_SOURCE_PREPARATION.json is a source-only record, not a compiled-build attestation. BETA8_BUILD_SOURCE_MANIFEST.json is historical Beta 8 evidence.
3. Prepare the Windows ZIP from the supplied EXE unchanged, with required support/profiles/license and release notes. Verify that its embedded EXE is byte-identical to the standalone EXE.
4. Publish matching source as the target commit and tag only after checks pass. Stage a draft prerelease, upload exactly the EXE, Windows ZIP and their two `.sha256.txt` files. GitHub's automatic source ZIP/TAR must resolve to the verified target commit. Do not publish a source-only/empty release or substitute a patch ZIP for the program.
5. Use the repository's connected GitHub tools and existing-build Actions transfer method; no secrets in files and no forced/reset push. Keep publication separate from compiling. Reuse already-verified staged assets rather than repeatedly recreating them.
6. Finalize as a public prerelease, download all four public assets without authentication, compare SHA-256 and byte sizes, extract the ZIP EXE and compare it again, verify tag/commit/source-manifest agreement, then report URLs, commit, tag, workflow run, and hashes.
7. Only after assets are genuinely public, update README's current-download link from Beta 8 to Beta 8.1. Do not describe tests or Windows/game validation that were not actually run.

Release wording should cover the standard OSM woodland/woodchip fix and separated tree-point control. Keep the inherited Beta 8 features. Do not mention donor-course names or unrelated utilities.
