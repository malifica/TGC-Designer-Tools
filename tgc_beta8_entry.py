"""TGC Designer Tools 2K25 Beta 8.4 entry point."""
import sys

if '--verify-graduated-background' in sys.argv:
    from VERIFY_BETA8_4_GRADUATED_BACKGROUND import verify
    verify()
elif '--verify-theme-planting' in sys.argv:
    from VERIFY_BETA8_THEME_PLANTING import verify
    verify()
else:
    # Preserve every existing import/verification route and normal GUI startup.
    import tgc_tree_size_test1_entry
