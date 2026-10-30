# Beta 8.1 publication handoff

## Prepared source, not published Windows assets

Repository: `malifica/TGC-Designer-Tools`. Source preparation starts from Beta 8 commit `670e7aa57a19d6a6228718e40c6b846e34e72034`. Read current `main` and its preparation manifest to identify the resulting commit. The publication-control branch is `release/beta8.1-publication`; do not rerun its source-preparation workflow after main has advanced.

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

## Required input

Look for the user's newly supplied `TGC_BETA8_1_EXISTING_BUILD_AND_SOURCE_*.zip` in the current conversation or Library. It must contain `dist/tgc_gui_2k25_beta8_1.exe`, matching application source, profiles/build support, and `UPLOAD_MANIFEST.json`. A Beta 8 archive is not a substitute. No Beta 8.1 EXE was created by source preparation.

If no Beta 8.1 build exists, provide the normal Windows CMD build/collect commands from BUILD_WINDOWS.md and ask for the resulting ZIP. Once it exists, do not build it again for publication.

## Verify and publish

1. Verify every upload-manifest entry and record the supplied EXE SHA-256. Check its PE header, embedded release identity, required standard-OSM code and independent woodland/tree options. Compare matching Python source against frozen modules using the same Python bytecode version; do not compare Python 3.11 and 3.13 marshalled code naively. Include packaged regional profiles and supporting assets.
2. Reconcile the actual build's source with current main. Do not overwrite newer source, drop unrelated updates, or label a mismatched tree as matching. BETA8_1_SOURCE_PREPARATION.json is a source-only record, not a compiled-build attestation. BETA8_BUILD_SOURCE_MANIFEST.json is historical Beta 8 evidence.
3. Prepare the Windows ZIP from the supplied EXE unchanged, with required support/profiles/license and release notes. Verify that its embedded EXE is byte-identical to the standalone EXE.
4. Publish matching source as the target commit and tag only after checks pass. Stage a draft prerelease, upload exactly the EXE, Windows ZIP and their two `.sha256.txt` files. GitHub's automatic source ZIP/TAR must resolve to the verified target commit. Do not publish a source-only/empty release or substitute a patch ZIP for the program.
5. Use the repository's connected GitHub tools and existing-build Actions transfer method; no secrets in files and no forced/reset push. Keep publication separate from compiling. Reuse already-verified staged assets rather than repeatedly recreating them.
6. Finalize as a public prerelease, download all four public assets without authentication, compare SHA-256 and byte sizes, extract the ZIP EXE and compare it again, verify tag/commit/source-manifest agreement, then report URLs, commit, tag, workflow run, and hashes.
7. Only after assets are genuinely public, update README's current-download link from Beta 8 to Beta 8.1. Do not describe tests or Windows/game validation that were not actually run.

Release wording should cover the standard OSM woodland/woodchip fix and separated tree-point control. Keep the inherited Beta 8 features. Do not mention donor-course names or unrelated utilities.
