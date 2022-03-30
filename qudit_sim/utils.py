from typing import Callable, Union, Any
import sys
import tempfile
import enum
import numpy as np
import h5py

twopi = 2. * np.pi

time_units = ['s', 'ms', 'us', 'ns']

class FrequencyScale(enum.Enum):
    Hz = 0
    kHz = 1
    MHz = 2
    GHz = 3
    
    @property
    def frequency_value(self):
        return np.power(10., 3 * self.value)
    
    @property
    def frequency_unit(self):
        return self.name
    
    @property
    def pulsatance_value(self):
        return self.frequency_value * twopi
    
    @property
    def pulsatance_unit(self):
        return self.name.replace('Hz', 'rad/s')
    
    @property
    def time_unit(self):
        return time_units[self.value]

SAVE_ERRORS = True
    
def matrix_ufunc(
    op: Callable,
    mat: Any,
    hermitian: bool = False,
    with_diagonals: bool = False,
    npmod=np
) -> np.ndarray:
    """Apply a unitary-invariant unary matrix operator to an array of normal matrices.
    
    The argument `mat` must be an array of normal matrices (in the last two dimensions). This function
    unitary-diagonalizes the matrices, applies `op` to the diagonals, and inverts the diagonalization.
    
    Args:
        op: Unary operator to be applied to the diagonals of `mat`.
        mat: Array of normal matrices (shape (..., n, n)). No check on normality is performed.
        with_diagonals: If True, also return the array `op(eigenvalues)`.

    Returns:
        An array corresponding to `op(mat)`. If `diagonals==True`, another array corresponding to `op(eigvals)`.
    """
    try:
        if hermitian:
            eigvals, eigcols = npmod.linalg.eigh(mat)
        else:
            eigvals, eigcols = npmod.linalg.eig(mat)
    except:
        if SAVE_ERRORS:
            with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as tmpf:
                pass

            with h5py.File(tmpf.name, 'w') as out:
                out.create_dataset('matrices', data=mat)
                
            sys.stderr.write(f'Error in eigendecomposition. Matrix saved at {tmpf.name}\n')
            
        raise
        
    eigrows = npmod.conjugate(npmod.moveaxis(eigcols, -2, -1))

    op_eigvals = op(eigvals)
    
    op_mat = npmod.matmul(eigcols * op_eigvals[..., None, :], eigrows)

    if with_diagonals:
        return op_mat, op_eigvals
    else:
        return op_mat
