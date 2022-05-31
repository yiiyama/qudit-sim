from typing import Union, Optional

import numpy as np
from rqutils import ArrayType
from rqutils.math import matrix_exp, matrix_angle
import rqutils.paulis as paulis

def get_ilogus_and_valid_it(unitaries):
    ## Compute ilog(U(t))
    ilogus, ilogvs = matrix_angle(unitaries, with_diagonals=True)
    ilogus *= -1.

    ## Find the first t where an eigenvalue does a 2pi jump
    last_valid_it = ilogus.shape[0]
    for ilogv_ext in [np.amin(ilogvs, axis=1), -np.amax(ilogvs, axis=1)]:
        margin = 0.1
        hits_minus_pi = np.asarray(ilogv_ext < -np.pi + margin).nonzero()[0]
        if len(hits_minus_pi) != 0:
            last_valid_it = min(last_valid_it, hits_minus_pi[0])

    return ilogus, ilogvs, last_valid_it


def make_heff_t(
    heff: ArrayType,
    tlist: Union[ArrayType, float],
    npmod=np
) -> ArrayType:
    tlist = npmod.asarray(tlist)
    tdims = (1,) * len(tlist.shape)
    return tlist[..., None, None] * heff.reshape(tdims + heff.shape)


def compose_ueff(
    heff_compos: ArrayType,
    basis_list: ArrayType,
    tlist: Union[ArrayType, float] = 1.,
    phase_factor: float = -1.,
    compos_offset: Optional[ArrayType] = None,
    npmod=np
) -> ArrayType:
    basis_list = basis_list.reshape(-1, *basis_list.shape[-2:])
    heff_compos = heff_compos.reshape(-1)
    heff = npmod.tensordot(basis_list, heff_compos, (0, 0))

    heff_t = make_heff_t(heff, tlist, npmod=npmod)

    if not isinstance(compos_offset, type(None)):
        compos_offset = compos_offset.reshape(-1)
        heff_t += npmod.tensordot(basis_list, compos_offset, (0, 0))

    return matrix_exp(phase_factor * 1.j * heff_t, hermitian=-1, npmod=npmod)


def heff_fidelity(
    time_evolution: ArrayType,
    heff_compos: ArrayType,
    basis_list: ArrayType,
    tlist: ArrayType,
    compos_offset: Optional[ArrayType] = None,
    npmod=np
) -> ArrayType:
    ueffdag_t = compose_ueff(heff_compos, basis_list, tlist, phase_factor=1., compos_offset=compos_offset,
                             npmod=npmod)

    tr_u_ueffdag = npmod.trace(npmod.matmul(time_evolution, ueffdag_t), axis1=1, axis2=2)
    fidelity = (npmod.square(tr_u_ueffdag.real) + npmod.square(tr_u_ueffdag.imag)) / (ueffdag_t.shape[-1] ** 2)

    return fidelity
