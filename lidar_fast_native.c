#include <stdint.h>
#include <stddef.h>
#include <math.h>

#ifdef _WIN32
#define TGC_API __declspec(dllexport)
#else
#define TGC_API __attribute__((visibility("default")))
#endif

/*
 * Exact scalar implementation of the historical TGCTool per-point terrain
 * accumulator. Output state is float32 exactly like the NumPy images; source
 * elevations/visual values are float64 exactly like GeoPointCloud points.
 * Point order is preserved.
 */
TGC_API int tgc_lidar_accumulate(
    const int32_t *rows,
    const int32_t *cols,
    const double *z,
    const double *visual,
    size_t count,
    int height,
    int width,
    float *elevation_out,
    float *visual_out
) {
    if (!rows || !cols || !z || !visual || !elevation_out || !visual_out ||
        height <= 0 || width <= 0) {
        return -1;
    }

    for (size_t i = 0; i < count; ++i) {
        int r = rows[i];
        int c = cols[i];
        if (r < 0 || c < 0 || r >= height || c >= width) {
            continue;
        }

        size_t idx = (size_t)r * (size_t)width + (size_t)c;

        float vv = visual_out[idx];
        if (isnan(vv)) {
            visual_out[idx] = (float)visual[i];
        } else {
            double next_v = (visual[i] - (double)vv) * 0.3 + (double)vv;
            visual_out[idx] = (float)next_v;
        }

        float ee = elevation_out[idx];
        if (isnan(ee)) {
            elevation_out[idx] = (float)z[i];
        } else {
            double alpha = (z[i] < (double)ee) ? 0.4 : 0.1;
            double next_e = (z[i] - (double)ee) * alpha + (double)ee;
            elevation_out[idx] = (float)next_e;
        }
    }

    return 0;
}
