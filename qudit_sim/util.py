from typing import Union, Tuple
import enum
from dataclasses import dataclass
import numpy as np

from rqutils.qprint import QPrintBraKet, LaTeXRepr

@dataclass(frozen=True)
class PulseSimResult:
    """Return type of pulse_sim.

    See the docstring of pulse_sim for why this class is necessary.
    """
    times: np.ndarray
    expect: Union[np.ndarray, None]
    states: Union[np.ndarray, None]
    dim: Tuple[int, ...]


_time_units = ['s', 'ms', 'us', 'ns']

class FrequencyScale(enum.Enum):
    """Frequency and corresponding time units."""
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
        return self.frequency_value * 2. * np.pi

    @property
    def pulsatance_unit(self):
        return self.name.replace('Hz', 'rad/s')

    @property
    def time_value(self):
        return np.power(10., -3 * self.value)

    @property
    def time_unit(self):
        return _time_units[self.value]


def print_hamiltonian(hamiltonian, has_static=True, phase_norm=(np.pi, 'π')):
    """IPython printer of the Hamiltonian list generated by HamiltonianGenerator."""

    lines = []
    start = 0
    if has_static:
        lines.append(QPrintBraKet(hamiltonian[0].full(), dim=hamiltonian[0].dims[0], lhs_label=r'H_{\mathrm{static}} &').latex(env=None))
        start += 1

    for iterm, term in enumerate(hamiltonian[start:]):
        lines.append(QPrintBraKet(term[0], dim=term[0].dims[0], lhs_label=f'H_{{{iterm}}} &', amp_norm=(1., fr'[\text{{{term[1]}}}]*'), phase_norm=phase_norm).latex(env=None))

    return LaTeXRepr(r'\begin{align}' + r' \\ '.join(lines) + r'\end{align}')
