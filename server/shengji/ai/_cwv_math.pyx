"""Optional libc-erf array loop; no approximate activation or fast-math."""
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
