"""Build Beta 8.1 through the retained, fully checked Beta 8 build pipeline."""
import sys
from BUILD_TGC_2K25_BETA8 import main
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('BUILD FAILED: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
