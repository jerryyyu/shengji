"""Optional array kernels for model inference."""
import numpy as np
cimport cython
from libc.math cimport erf


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


@cython.boundscheck(False)
@cython.wraparound(False)
def bias_relu_inplace(float[:, ::1] rows not None, const float[::1] bias not None):
    """Add the per-column bias and rectify each contiguous float32 row."""
    cdef Py_ssize_t i, j, height = rows.shape[0], width = rows.shape[1]
    cdef float value, overflow_margin = 2.0 ** 103
    if bias.shape[0] != width:
        raise ValueError("bias width differs from row width")
    # At the top of float32, half an ulp is 2**103. Larger biases can
    # overflow on addition, so let NumPy apply its floating-point error policy.
    for j in range(width):
        if not -overflow_margin < bias[j] < overflow_margin:
            array = np.asarray(rows)
            array += np.asarray(bias)
            np.maximum(array, 0.0, out=array)
            return
    with nogil:
        for i in range(height):
            for j in range(width):
                value = rows[i, j] + bias[j]
                rows[i, j] = 0.0 if value <= 0.0 else value
