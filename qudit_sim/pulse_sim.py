from typing import Any, Dict, List, Tuple, Sequence, Optional, Union
import os
import tempfile
import numpy as np
import qutip as qtp

from .hamiltonian import RWAHamiltonianGenerator

DriveDef = Dict[Union[int, str], Dict[str, Any]]

def run_pulse_sim(
    qubits: Sequence[int],
    params: Dict[str, Any],
    drive_def: Dict,
    psi0: qtp.Qobj = qtp.basis(2, 0),
    tlist: Union[np.ndarray, Tuple[int, int]] = (10, 100),
    force_array: bool = False,
    e_ops: Optional[Sequence[Any]] = None,
    options: Optional[qtp.solver.Options] = None,
    progress_bar: Optional[qtp.ui.progressbar.BaseProgressBar] = None,
    save_result_to: Optional[str] = None
) -> qtp.solver.Result:
    """Run a pulse simulation.

    Args:
        qubits: List of qudits to include in the Hamiltonian.
        params: Hamiltonian parameters. See the docstring of RWAHamiltonian for details.
        drive_def: Drive definition dict. Keys are qubit ids and values are dicts of format
            `{'frequency': frequency, 'amplitude': amplitude}`. Can optionally include a key `'args'` where the
            corresponding value is then passed to the `args` argument of `sesolve`.
        psi0: Initial state Qobj.
        tlist: Time points to use in the simulation or a pair `(points_per_cycle, num_cycles)` where in the latter
            case the cycle of the fastest oscillating term in the Hamiltonian will be used.
        force_array: Use an array-based Hamiltonian for the simulation. May run faster but potentially give
            inaccurate results, depending on the Hamiltonian.
        e_ops: List of observables passed to the QuTiP solver.
        options: QuTiP solver options.
        progress_bar: QuTiP progress bar.
        save_result_to: File name (without the extension) to save the simulation result to.

    Returns:
        Result of running `qutip.sesolve`.
    """
    ## Collect kwargs passed directly to sesolve
    
    kwargs = {'e_ops': e_ops, 'options': options, 'progress_bar': progress_bar}
    
    ## Make the Hamiltonian
    
    num_sim_levels = psi0.dims[0][0]
    
    # When using the array Hamiltonian, Hint terms should be kept as python functions which
    # yield the arrays upon calling array_hamiltonian().
    hgen = RWAHamiltonianGenerator(qubits, params, num_sim_levels, compile_hint=(not force_array))
    
    for key, value in drive_def.items():
        if key == 'args':
            kwargs['args'] = value
            continue
            
        hgen.add_drive(key, frequency=value['frequency'], amplitude=value['amplitude'])

    if isinstance(tlist, tuple):
        tlist = hgen.make_tlist(*tlist)

    if force_array or hgen.need_tlist:
        hamiltonian = hgen.array_generate(tlist)
    else:
        hamiltonian = hgen.generate()
            
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tempdir:
        os.chdir(tempdir)
        result = qtp.sesolve(hamiltonian, psi0, tlist, **kwargs)
        os.chdir(cwd)

    if save_result_to:
        qtp.fileio.qsave(result, save_result_to)
        
    return result
