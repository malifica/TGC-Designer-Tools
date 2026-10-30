"""TGC Designer Tools 2K25 Beta 8.1 entry point."""
import sys

if '--verify-theme-planting' in sys.argv:
    from VERIFY_BETA8_THEME_PLANTING import verify
    verify()
else:
    # Preserve every existing import/verification route and normal GUI startup.
    import tgc_tree_size_test1_entry
