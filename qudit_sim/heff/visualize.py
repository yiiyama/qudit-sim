"""Visualization routines for effective Hamiltonian studies."""

from typing import Optional, Tuple, List, Sequence, Union
import logging
import numpy as np
from IPython.display import Latex
import h5py
import scipy.optimize as sciopt
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.markers import MarkerStyle

import rqutils.paulis as paulis
from rqutils.math import matrix_exp, matrix_angle

from ..util import FrequencyScale
from .common import make_heff_t, heff_fidelity

def inspect_fidelity_maximization(
    filename: str,
    threshold: float = 0.01,
    tscale: FrequencyScale = FrequencyScale.auto,
    align_ylim: bool = False,
    limit_components: Optional[List[Tuple]] = None,
    digest: bool = True
) -> List[mpl.figure.Figure]:
    """Plot the time evolution of Pauli components before and after fidelity maximization.

    Args:
        filename: Name of the HDF5 file containing the fit result.
        threshold: Threshold for a Pauli component to be plotted, in radians. Ignored if
            limit_components is not None.
        tscale: Scale for the time axis.
        align_ylim: Whether to align the y axis limits for all plots.
        limit_components: List of Pauli components to plot.
        digest: If True, a figure for fit information is included.

    Returns:
        A list of two (three if digest=True) figures.
    """
    with h5py.File(filename, 'r') as source:
        num_qudits = int(source['num_qudits'][()])
        num_sim_levels = int(source['num_sim_levels'][()])
        comp_dim = int(source['comp_dim'][()])
        time_evolution = source['time_evolution'][()]
        tlist = source['tlist'][()]
        if num_sim_levels != comp_dim:
            components = source['components_original'][()]
        else:
            components = source['components'][()]

        try:
            loss = source['loss'][()]
            grad = source['grad'][()]
        except KeyError:
            loss = None
            grad = None

    dim = (num_sim_levels,) * num_qudits
    num_paulis = num_sim_levels ** 2
    pauli_dim = (num_paulis,) * num_qudits

    if tscale is FrequencyScale.auto:
        tscale = FrequencyScale.find_time_scale(tlist[-1])

    tlist *= tscale.frequency_value
    components[0] /= tscale.frequency_value
    adjustments /= tscale.frequency_value

    ilogus = -matrix_angle(time_evolution)
    ilogu_compos = paulis.components(ilogus, dim=dim).real
    ilogu_compos = ilogu_compos.reshape(tlist.shape[0], -1)[:, 1:]

    heff = paulis.compose(components[0], dim=dim)
    heff_t = make_heff_t(heff, tlist)
    heff_t += paulis.compose(components[1], dim=dim)

    ueff_dagger = matrix_exp(1.j * heff_t, hermitian=-1)

    target = np.matmul(time_evolution, ueff_dagger)
    ilogtargets, ilogvs = matrix_angle(target, with_diagonals=True)
    ilogtargets *= -1.
    ilogtarget_compos = paulis.components(ilogtargets, dim=dim).real
    ilogtarget_compos = ilogtarget_compos.reshape(tlist.shape[0], -1)[:, 1:]

    if limit_components is None:
        # Make a list of tuples from a tuple of arrays
        indices_ilogu = np.nonzero(np.amax(np.abs(ilogu_compos), axis=0) > threshold)[0] + 1
        indices_ilogu = np.concatenate([np.array([0]), indices_ilogu])
        indices_ilogtarget = np.nonzero(np.amax(np.abs(ilogtarget_compos), axis=0) > threshold)[0] + 1
        indices_ilogtarget = np.concatenate([np.array([0]), indices_ilogtarget])
    else:
        tuple_of_indices = tuple([index[i] for index in limit_components]
                                 for i in range(len(limit_components[0])))
        limit_components = np.ravel_multi_index(tuple_of_indices, pauli_dim)
        limit_components = np.sort(limit_components)

        indices_ilogu = limit_components
        indices_ilogtarget = limit_components

    figures = []

    ## First figure: original time evolution and Heff
    fig, axes = _make_figure(len(indices_ilogu))
    figures.append(fig)
    fig.suptitle(r'Original time evolution vs $H_{eff}$', fontsize=24)

    _plot_ilogu_compos(axes, ilogu_compos, num_qudits, num_sim_levels, indices_ilogu, tlist, tscale,
                       comp_dim, align_ylim=align_ylim)

    ## Add lines with slope=compo for terms above threshold
    for iax, basis_index_flat in enumerate(indices_ilogu):
        ax = axes[iax]
        basis_index = np.unravel_index(basis_index_flat, pauli_dim)
        central = components[(0,) + basis_index] * tlist
        line = ax.plot(tlist, central)
        ax.plot(tlist, central - components[(2,) + basis_index], ls='--', color=line.color)
        ax.plot(tlist, central + components[(2,) + basis_index], ls='--', color=line.color)

    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

    handles = [
        mpl.lines.Line2D([0.], [0.], color=colors[0]),
        mpl.lines.Line2D([0.], [0.], color=colors[1])
    ]
    labels = [
        'ilogU(t) component',
        '$H_{eff}t$ component $\pm$ offset'
    ]
    fig.legend(handles, labels, 'upper right')

    ## Second figure: subtracted unitaries
    fig, axes = _make_figure(len(indices_ilogtarget))
    figures.append(fig)
    fig.suptitle('Unitary-subtracted time evolution', fontsize=24)

    ## Plot individual pauli components
    _plot_ilogu_compos(axes, ilogtarget_compos, num_qudits, num_sim_levels, indices_ilogtarget,
                       tlist, tscale, comp_dim, align_ylim=align_ylim)

    if digest:
        ## Third figure: fit digest plots
        fig, axes = plt.subplots(1, 4, figsize=(16, 4))
        figures.append(fig)
        fig.suptitle('Fit metrics', fontsize=24)

        # fidelity
        final_fidelity = heff_fidelity(time_evolution, components[0], components[1],
                                       paulis.paulis(dim), tlist)
        ax = axes[0]
        ax.set_title('Final fidelity')
        ax.set_xlabel(f't ({tscale.time_unit})')
        ax.set_ylabel('fidelity')
        ax.plot(tlist, final_fidelity)
        ax.axhline(1., color='black', linewidth=0.5)

        # eigenphases of target matrices
        ax = axes[1]
        ax.set_title('Final target matrix eigenphases')
        ax.set_xlabel(f't ({tscale.time_unit})')
        ax.set_ylabel(r'$U(t)U_{eff}^{\dagger}(t)$ eigenphases')
        ax.plot(tlist, ilogvs)

        ## Intermediate data is not available if minuit is used
        if loss is not None:
            ax = axes[2]
            ax.set_title('Loss evolution')
            ax.set_xlabel('steps')
            ax.set_ylabel('loss')
            ax.plot(loss)
            ax.axhline(0., color='black', linewidth=0.5)

            ax = axes[3]
            ax.set_title('Gradient evolution')
            ax.set_xlabel('steps')
            ax.set_ylabel('max(abs(grad))')
            ax.plot(np.amax(np.abs(grad), axis=1))
            ax.axhline(0., color='black', linewidth=0.5)

    for fig in figures:
        fig.tight_layout()

    return figures


def _make_figure(num_axes, nxmin=4, nxmax=12):
    nx = np.floor(np.sqrt(num_axes)).astype(int)
    nx = max(nx, nxmin)
    nx = min(nx, nxmax)
    ny = np.ceil(num_axes / nx).astype(int)

    fig, axes = plt.subplots(ny, nx, figsize=(nx * 4, ny * 4))
    return fig, axes.reshape(-1)


def _plot_ilogu_compos(axes, compos_data, num_qudits, num_sim_levels, limit_components_flat, tlist, tscale, comp_dim, align_ylim=False):
    # compos_data: shape (T, num_basis - 1)
    # limit_components_flat
    num_paulis = num_sim_levels ** 2
    num_comp_paulis = comp_dim ** 2
    dim = (num_sim_levels,) * num_qudits
    pauli_dim = (num_paulis,) * num_qudits

    limit_components = np.unravel_index(limit_components_flat, pauli_dim)
    labels = paulis.labels(dim, norm=False)[limit_components]
    compos_data_selected = compos_data[:, limit_components_flat - 1]

    iax = 0

    if limit_components_flat[0] == 0:
        l0p = paulis.l0_projector(comp_dim, num_sim_levels)
        l0_projection = l0p
        for _ in range(num_qudits - 1):
            l0_projection = np.kron(l0_projection, l0p)

        l0_compos = np.matmul(compos_data, l0_projection[1:])

        # lambda 0 projection onto computational subspace
        ax = axes[0]
        title = f'${labels[0]}$'
        if comp_dim != num_sim_levels:
            title += ' (projected)'
        ax.set_title(title)
        ax.plot(tlist, l0_compos)

        iax += 1

    while iax < limit_components_flat.shape[0]:
        ax = axes[iax]

        ax.set_title(f'${labels[iax]}$')
        ax.plot(tlist, compos_data_selected[:, iax])

        if (np.array([indices[iax] for indices in limit_components]) < num_comp_paulis).all():
            for spine in ax.spines.values():
                spine.set(linewidth=2.)

        iax += 1

    ymax = np.amax(compos_data_selected)
    ymin = np.amin(compos_data_selected)
    vrange = ymax - ymin
    ymax += 0.2 * vrange
    ymin -= 0.2 * vrange

    for ax in axes.reshape(-1):
        ax.axhline(0., color='black', linewidth=0.5)
        if align_ylim:
            ax.set_ylim(ymin, ymax)
        ax.set_xlabel(f't ({tscale.time_unit})')
        ax.set_ylabel('rad')


def plot_amplitude_scan(
    amplitudes: np.ndarray,
    components: Sequence,
    threshold: Optional[float] = None,
    amp_scale: FrequencyScale = FrequencyScale.auto,
    compo_scale: FrequencyScale = FrequencyScale.auto,
    max_poly_order: int = 4
) -> Tuple[mpl.figure.Figure, np.ndarray, FrequencyScale, FrequencyScale]:
    """Plot the result of the amplitude scan.

    See the last example in examples/validation/heff.ipynb for how to prepare the inputs to this function.

    This function performs polynomial fits to the amplitude dependences of the Pauli components and returns
    the best-fit parameters as well as adds the fit curves to the plots. Amplitude variable in the polynomials
    are normalized to O(1) to avoid numerical errors. The third and fourth return values of this function
    represent the amplitude and component scales used for the normalization.

    Args:
        amplitudes: Array of drive amplitudes (assumed real)
        components: Returned list of effective Hamiltonian components from find_heff.
        threshold: Only plot components whose maximum is above this threshold. Defaults to
            `0.01 * compo_scale.pulsatance_value`.
        amp_scale: Scale of the drive amplitude.
        compo_scale: Scale of the components.
        max_poly_order: Maximum polynomial order for fitting the amplitude dependencies of the components.

    Returns:
        Plot Figure, polynomial coefficients from the fits, and the amplitude and components scale used to
        normalize the amplitude variable in the polynomials.
    """
    components = np.asarray(components)
    heff_compos = components[:, 0]

    num_qudits = len(heff_compos.shape) - 1 # first dim: amplitudes
    comp_dim = int(np.around(np.sqrt(heff_compos.shape[1])))
    num_paulis = comp_dim ** 2

    if amp_scale is FrequencyScale.auto:
        amp_scale = FrequencyScale.find_energy_scale(np.amax(np.abs(amplitudes)))

    amp_scale_omega = amp_scale.pulsatance_value
    amps_norm = amplitudes / amp_scale_omega

    if compo_scale is FrequencyScale.auto:
        compo_scale = FrequencyScale.find_energy_scale(np.amax(np.abs(heff_compos)))

    compo_scale_omega = compo_scale.pulsatance_value
    compos_norm = heff_compos / compo_scale_omega

    if threshold is None:
        threshold = compo_scale_omega * 1.e-2

    threshold /= compo_scale_omega

    # Amplitude, compo, and threshold are all divided by omega and are in terms of frequency

    amax = np.amax(np.abs(compos_norm), axis=0)
    num_above_threshold = np.count_nonzero(amax > threshold)
    min_max = np.amin(np.where(amax > threshold, amax, np.amax(amax)))

    # Mask to apply to the components array

    plot_mask = np.where(amax > threshold, 1, 0)
    plot_mask = np.where(amax > 50. * min_max, 2, plot_mask)

    # Array for polynomial fit results

    coefficients = np.zeros(components.shape[1:] + (max_poly_order + 1,), dtype=float)

    if num_qudits > 1 and num_above_threshold > 6:
        # Which Pauli components of the first qudit have plots to draw?
        has_passing_compos = np.any(amax.reshape(num_paulis, -1) > threshold, axis=1)
        num_plots = np.sum(has_passing_compos)

        nv = np.ceil(np.sqrt(num_plots)).astype(int)
        nh = np.ceil(num_plots / nv).astype(int)
        fig, axes = plt.subplots(nv, nh, figsize=(16, 12))

        prefixes = paulis.labels(comp_dim, symbol='', norm=False)

        iax = 0

        for ip in range(num_paulis):
            if not has_passing_compos[ip]:
                continue

            ax = axes.reshape(-1)[iax]
            _plot_amplitude_scan_on(ax, amps_norm, compos_norm[:, ip], plot_mask[ip],
                                    max_poly_order, coefficients[ip], prefix=prefixes[ip])

            iax += 1

    else:
        num_plots = 1
        fig, axes = plt.subplots(1, 1, squeeze=False)
        _plot_amplitude_scan_on(axes[0, 0], amps_norm, compos_norm, plot_mask, max_poly_order, coefficients)

    cmax = np.amax(compos_norm, axis=0)
    cmin = np.amin(compos_norm, axis=0)
    ymax = np.amax(np.where(plot_mask == 2, cmax * 0.1, cmax))
    ymin = np.amin(np.where(plot_mask == 2, cmin * 0.1, cmin))

    for ax in axes.reshape(-1)[:num_plots]:
        ax.set_ylim(ymin * 1.2, ymax * 1.2)
        ax.grid(True)
        # Since amp and nu are normalized by (2*pi*frequency), displayed values are frequencies
        ax.set_xlabel(f'Drive amplitude ({amp_scale.frequency_unit})')
        ax.set_ylabel(fr'$\nu$ ({compo_scale.frequency_unit})')
        ax.legend()

    fig.tight_layout()

    return fig, coefficients, amp_scale, compo_scale


def _plot_amplitude_scan_on(ax, amps_norm, compos_norm, plot_mask, max_poly_order, coefficients, prefix=''):
    num_qudits = len(compos_norm.shape) - 1 # first dimension: amplitudes
    comp_dim = int(np.around(np.sqrt(compos_norm.shape[1])))

    basis_labels = paulis.labels((comp_dim,) * num_qudits, symbol='',
                                 delimiter=('' if comp_dim == 2 else ','), norm=False)

    amps_norm_fine = np.linspace(amps_norm[0], amps_norm[-1], 100)
    num_amps = amps_norm.shape[0]

    filled_markers = MarkerStyle.filled_markers
    num_markers = len(filled_markers)

    imarker = 0

    for index in np.ndindex(compos_norm.shape[1:]):
        if plot_mask[index] == 0:
            continue

        if comp_dim == 2:
            label = prefix + basis_labels[index]
        else:
            if prefix:
                label = f'{prefix},{basis_labels[index]}'
            else:
                label = basis_labels[index]

        plot_label = f'${label}$'

        if plot_mask[index] == 2:
            plot_scale = 0.1
            plot_label += r' ($\times 0.1$)'
        else:
            plot_scale = 1.

        compos = compos_norm[(slice(None),) + index]

        pathcol = ax.scatter(amps_norm, compos * plot_scale, marker=filled_markers[imarker % num_markers], label=plot_label)

        imarker += 1

        # Perform a polynomial fit

        even = np.sum(compos[:num_amps // 2] * compos[-num_amps // 2:]) > 0.

        if even:
            curve = _poly_even
            p0 = np.zeros(max_poly_order // 2 + 1)
        else:
            curve = _poly_odd
            p0 = np.zeros((max_poly_order + 1) // 2)

        try:
            popt, _ = sciopt.curve_fit(curve, amps_norm, compos, p0=p0)
        except RuntimeError:
            logging.warning(f'Components for {label} could not be fit with an order {max_poly_order} polynomial.')
            continue
        except OptimizeWarning:
            logging.warning(f'Covariance of the fit parameters for {label} could not be determined.')

        if even:
            coefficients[index][::2] = popt
        else:
            coefficients[index][1::2] = popt

        ax.plot(amps_norm_fine, curve(amps_norm_fine, *popt) * plot_scale, color=pathcol.get_edgecolor())

def _poly_even(x, *args):
    value = args[0]
    for iarg, arg in enumerate(args[1:]):
        value += arg * np.power(x, 2 * (iarg + 1))
    return value

def _poly_odd(x, *args):
    value = 0.
    for iarg, arg in enumerate(args):
        value += arg * np.power(x, 2 * iarg + 1)
    return value


def print_amplitude_scan(
    coefficients: np.ndarray,
    amp_scale: FrequencyScale,
    compo_scale: FrequencyScale
) -> Latex:
    """Print a LaTeX expression of the amplitude scan fit results.

    Args:
        coefficients: array of polynomial coefficients given by plot_amplitude_scan.
        amp_scale: Amplitude normalization scale.
        compo_scale: Pauli components normalization scale.

    Returns:
        A LaTeX representation of the polynomials.
    """
    num_qudits = len(coefficients.shape) - 1 # last dimension is for polynomial coefficients
    comp_dim = int(np.around(np.sqrt(coefficients.shape[0])))

    basis_labels = paulis.labels((comp_dim,) * num_qudits, symbol='',
                                 delimiter=('' if comp_dim == 2 else ','), norm=False)

    poly_order = coefficients.shape[-1]

    lines = []

    for index in np.ndindex(coefficients.shape[:-1]):
        if np.allclose(coefficients[index], np.zeros(poly_order)):
            continue

        line = fr'\frac{{\nu_{{{basis_labels[index]}}}}}{{\mathrm{{{compo_scale.frequency_unit}}}}} &='

        for order, p in enumerate(coefficients[index]):
            if p == 0.:
                continue

            pstr = f'{abs(p):.2e}'
            epos = pstr.index('e')
            power = int(pstr[epos + 1:])
            if power == -1:
                pexp = f'{abs(p):.3f}'
            elif power == 0:
                pexp = f'{abs(p):.2f}'
            elif power == 1:
                pexp = f'{abs(p):.1f}'
            else:
                pexp = fr'\left({pstr[:epos]} \times 10^{{{power}}}\right)'

            if p < 0.:
                pexp = f'-{pexp}'

            if order == 0:
                line += pexp
            elif order == 1:
                line += f'{pexp} A'
            else:
                if p > 0.:
                    pexp = f'+ {pexp}'
                line += f'{pexp} A^{order}'

        lines.append(line)

    linebreak = r' \\ '
    expr = Latex(fr'\begin{{align}}{linebreak.join(lines)}\end{{align}} A: amplitude in $\mathrm{{{amp_scale.frequency_unit}}}$')

    return expr
