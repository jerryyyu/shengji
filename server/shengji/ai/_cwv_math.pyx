"""Optional numeric loops for the NumPy inference runtimes."""
import numpy as np
cimport cython
from libc.math cimport erf
from libc.stdint cimport uintptr_t


@cython.boundscheck(False)
@cython.wraparound(False)
def erf_array(values):
    array = np.ascontiguousarray(values, dtype=np.float64)
    result = np.empty(array.shape, dtype=np.float64)
    cdef const double[::1] source = array.reshape(-1)
    cdef double[::1] dest = result.reshape(-1)
    cdef Py_ssize_t i, n = source.shape[0]
    with nogil:
        for i in range(n):
            dest[i] = erf(source[i])
    return result


cdef extern from *:
    """
    #include <fenv.h>
    #include <float.h>
    #include <math.h>

    #if (defined(__clang__) || defined(__GNUC__)) && FLT_EVAL_METHOD == 0 && !defined(__FAST_MATH__)
    #define SHENGJI_NORM_288 1
    static inline float shengji_sum72(const float *row)
    {
        float lanes[8];
        for (int lane = 0; lane < 8; ++lane)
            lanes[lane] = row[lane];
        for (int start = 8; start < 72; start += 8)
            for (int lane = 0; lane < 8; ++lane)
                lanes[lane] += row[start + lane];
        float left = (lanes[0] + lanes[1]) + (lanes[2] + lanes[3]);
        float right = (lanes[4] + lanes[5]) + (lanes[6] + lanes[7]);
        return left + right;
    }

    // The contiguous NumPy reduction splits a 288-wide row into four 72s.
    static inline float shengji_mean288(const float *row)
    {
        float left = shengji_sum72(row) + shengji_sum72(row + 72);
        float right = shengji_sum72(row + 144) + shengji_sum72(row + 216);
        return (0.0f + (left + right)) / 288.0f;
    }

    #if defined(__GNUC__) && !defined(__clang__)
    __attribute__((optimize("fp-contract=off")))
    #endif
    static int shengji_ln288(const float *restrict x, const float *restrict w,
                            const float *restrict b, float *restrict out,
                            float *restrict square, Py_ssize_t rows, float epsilon)
    {
        #if defined(__clang__)
        #pragma clang fp contract(off)
        #endif
        fenv_t previous;
        if (feholdexcept(&previous) != 0)
            return 0;
        for (Py_ssize_t i = 0; i < rows; ++i) {
            const float *input = x + i * 288;
            float *result = out + i * 288;
            float *squares = square + i * 288;
            float mean = shengji_mean288(input);
            for (int col = 0; col < 288; ++col) {
                float centered = input[col] - mean;
                result[col] = centered;
                squares[col] = centered * centered;
            }
            float scale = sqrtf(shengji_mean288(squares) + epsilon);
            for (int col = 0; col < 288; ++col) {
                float weighted = (result[col] / scale) * w[col];
                result[col] = weighted + b[col];
            }
        }
        // Let NumPy apply its usual seterr policy for exceptional arithmetic.
        int status = fetestexcept(FE_INVALID | FE_DIVBYZERO | FE_OVERFLOW | FE_UNDERFLOW);
        fesetenv(&previous);
        return status == 0;
    }
    #else
    #define SHENGJI_NORM_288 0
    #define shengji_ln288(x, w, b, out, square, rows, epsilon) 0
    #endif
    """
    int SHENGJI_NORM_288
    int shengji_ln288(const float *x, const float *w, const float *b, float *out,
                      float *square, Py_ssize_t rows, float epsilon) noexcept nogil


cdef inline bint _overlap(uintptr_t start, size_t length,
                          uintptr_t other, size_t other_length) noexcept:
    return other < start + length and start < other + other_length


@cython.boundscheck(False)
@cython.wraparound(False)
def layer_norm_288(x, w, b, out, square, float epsilon):
    """Write the fused readout norm when buffers match the native layout."""
    if not SHENGJI_NORM_288 or x.ndim != 2 or x.shape[1] != 288 or not x.shape[0]:
        return False
    for array in (x, w, b, out, square):
        if (type(array) is not np.ndarray or array.dtype != np.float32
                or not array.flags.c_contiguous or not array.flags.aligned):
            return False
    if (w.shape != (288,) or b.shape != (288,)
            or out.shape != x.shape or square.shape != x.shape
            or not out.flags.writeable or not square.flags.writeable):
        return False
    cdef const float[:, ::1] input_rows = x
    cdef const float[::1] weight = w, bias = b
    cdef float[:, ::1] result = out, squares = square
    cdef size_t row_bytes = 288 * sizeof(float)
    cdef size_t size = input_rows.shape[0] * row_bytes
    cdef uintptr_t src = <uintptr_t>&input_rows[0, 0]
    cdef uintptr_t dest = <uintptr_t>&result[0, 0]
    cdef uintptr_t scratch = <uintptr_t>&squares[0, 0]
    for address, length in ((src, size), (<uintptr_t>&weight[0], row_bytes),
                            (<uintptr_t>&bias[0], row_bytes)):
        if _overlap(dest, size, address, length) or _overlap(scratch, size, address, length):
            return False
    if _overlap(dest, size, scratch, size):
        return False
    cdef int success
    with nogil:
        success = shengji_ln288(&input_rows[0, 0], &weight[0], &bias[0],
                               &result[0, 0], &squares[0, 0], input_rows.shape[0], epsilon)
    return bool(success)
